import logging
import math
import os
import weakref
from typing import NamedTuple
from PySide6 import QtCore
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
)
from .....domain.entities import shape as shapes
from .....domain.entities.annotation import BidAnnotation
from .....domain.entities.condition import Condition
from .....domain.entities.named_view import named_view_position_from_bounds
from ....visualization.core.geometry.takeoff_geometry import (
    compute_count_vertices,
    compute_line_angle,
)
from ....visualization.pdf import ost_pdf
from ....visualization.pdf.renderers.annotation_item_renderer import (
    DIMENSION_FONT_SIZE_ADJUSTMENT,
    build_dimension_path,
    create_dimension_text_item,
)
from ....visualization.pdf.renderers.annotation_renderer import (
    calculate_dimension_geometry,
    create_cloud_path_points,
)
from ....utils.annotation_defaults import (
    PLACEABLE_ANNOTATION_TYPES,
    annotation_default_style,
    dimension_annotation_properties,
)
from ....visualization.pdf.pdfium_lock import pdfium_lock
from .geometry_utils import polygon_is_valid, polyline_self_intersects
from .handle_style import apply_takeoff_handle_style
from .snap_index import ENDPOINT, GRID, MIDPOINT, NONE, PERPENDICULAR, SnapIndex

logger = logging.getLogger(__name__)
_RIGHT_ANGLE_ALIGNMENT_TOLERANCE = 1e-6
_AREA_ANNOTATION_TYPES = frozenset({"polygon", "cloud"})
_INK_ANNOTATION_TYPES = frozenset({"ink"})
_POINT_ANNOTATION_TYPES = frozenset({"hotlink"})
_DRAG_ANNOTATION_TYPES = (
    PLACEABLE_ANNOTATION_TYPES
    - _AREA_ANNOTATION_TYPES
    - _INK_ANNOTATION_TYPES
    - _POINT_ANNOTATION_TYPES
)
_TEXT_SELECTION_OUTLINE_COLOR = QColor(128, 128, 128)


class AreaPlacementEndpoint(NamedTuple):
    final_x: float
    final_y: float
    right_angle_candidate_x: float
    right_angle_candidate_y: float
    right_angle_candidate_active: bool
    right_angle_indicator_active: bool


class PlacementModeMixin:
    def _snap_angle(
        self, origin_x: float, origin_y: float, target_x: float, target_y: float
    ) -> tuple[float, float]:
        snap_angle_deg = (
            self._mouse_pressed_snap_angle
            if QGuiApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier
            else self._mouse_unpressed_snap_angle
        )
        if snap_angle_deg <= 0:
            return target_x, target_y
        dx = target_x - origin_x
        dy = target_y - origin_y
        length = math.hypot(dx, dy)
        if length < 1e-9:
            return target_x, target_y
        angle = math.atan2(dy, dx)
        snap_angle_rad = math.radians(snap_angle_deg)
        snapped = round(angle / snap_angle_rad) * snap_angle_rad
        return origin_x + length * math.cos(snapped), origin_y + length * math.sin(
            snapped
        )

    def _right_angle_target_from_first_point(
        self, target_x: float, target_y: float
    ) -> tuple[float, float, bool]:
        if not self._snap_to_right_angle_enabled or not self._place_points:
            return target_x, target_y, False
        first_x, first_y = self._place_points[0]
        first_scene = self._ost_to_scene_pos(first_x, first_y)
        target_scene = self._ost_to_scene_pos(target_x, target_y)
        first_vp = self.mapFromScene(first_scene)
        target_vp = self.mapFromScene(target_scene)
        threshold_px = float(self._snap_to_right_angle_threshold_px)
        if threshold_px <= 0.0:
            return target_x, target_y, False
        snap_x = abs(target_vp.x() - first_vp.x()) <= threshold_px
        snap_y = abs(target_vp.y() - first_vp.y()) <= threshold_px
        if snap_x:
            target_x = first_x
        if snap_y:
            target_y = first_y
        return target_x, target_y, snap_x or snap_y

    def _is_right_angle_aligned_to_first_point(
        self, target_x: float, target_y: float
    ) -> bool:
        if not self._place_points:
            return False
        first_x, first_y = self._place_points[0]
        return (
            abs(target_x - first_x) <= _RIGHT_ANGLE_ALIGNMENT_TOLERANCE
            or abs(target_y - first_y) <= _RIGHT_ANGLE_ALIGNMENT_TOLERANCE
        )

    def _area_final_endpoint_for_placement(
        self,
        origin_x: float,
        origin_y: float,
        target_x: float,
        target_y: float,
        snap_kind: int,
    ) -> AreaPlacementEndpoint:
        right_x, right_y, right_angle_candidate_active = (
            self._right_angle_target_from_first_point(target_x, target_y)
        )
        candidate_x, candidate_y = target_x, target_y
        if right_angle_candidate_active:
            candidate_x, candidate_y = right_x, right_y
        final_x, final_y = self._snap_angle_for_placement(
            origin_x, origin_y, candidate_x, candidate_y, snap_kind
        )
        right_angle_indicator_active = (
            right_angle_candidate_active
            and self._is_right_angle_aligned_to_first_point(final_x, final_y)
        )
        return AreaPlacementEndpoint(
            final_x=final_x,
            final_y=final_y,
            right_angle_candidate_x=right_x,
            right_angle_candidate_y=right_y,
            right_angle_candidate_active=right_angle_candidate_active,
            right_angle_indicator_active=right_angle_indicator_active,
        )

    def _rectangle_position_from_corners(
        self, x1: float, y1: float, x2: float, y2: float
    ) -> list[float]:
        return [x1, y1, x2, y1, x2, y2, x1, y2]

    def _points_from_position(self, position: list[float]) -> list[tuple[float, float]]:
        return [(position[i], position[i + 1]) for i in range(0, len(position) - 1, 2)]

    def _snap_angle_for_placement(
        self,
        origin_x: float,
        origin_y: float,
        target_x: float,
        target_y: float,
        snap_kind: int,
    ) -> tuple[float, float]:
        snapped_x, snapped_y = self._snap_angle(origin_x, origin_y, target_x, target_y)
        if snap_kind != GRID:
            return snapped_x, snapped_y
        return self._snap_placement_distance(
            origin_x,
            origin_y,
            snapped_x,
            snapped_y,
        )

    def _snap_placement_distance(
        self,
        origin_x: float,
        origin_y: float,
        target_x: float,
        target_y: float,
    ) -> tuple[float, float]:
        snap_increment = float(self._snap_increments or 0.0)
        if snap_increment <= 0.0:
            return target_x, target_y
        dx = target_x - origin_x
        dy = target_y - origin_y
        length = math.hypot(dx, dy)
        if length < 1e-9:
            return target_x, target_y
        snapped_length = round(length / snap_increment) * snap_increment
        if snapped_length <= 0.0:
            return origin_x, origin_y
        scale = snapped_length / length
        return origin_x + dx * scale, origin_y + dy * scale

    def _invalidate_snap_index(self) -> None:
        self._takeoff_snap_index_dirty = True
        self._pdf_snap_index_dirty = True

    def _pdf_snap_available_for_current_page(self) -> bool:
        page = self._current_page
        return bool(
            page is not None
            and self._current_bid_page_uid == page.uid
            and self._load_geometry_ready
        )

    def _pdf_intelligence_source(self):
        page = self._current_page
        if not page or not page.layer_visible:
            return None
        overlay_enabled = (
            page.image_show_mode in (1, 2)
            and bool(page.overlay_image_path)
            and page.overlay_image_path.lower().endswith(".pdf")
        )
        if overlay_enabled:
            return ("overlay", page.overlay_image_path, 0)
        if page.image_path and page.image_path.lower().endswith(".pdf"):
            return ("main", page.image_path, int(page.page_index or 0))
        return None

    def _pdf_snap_cache_key(self):
        source = self._pdf_intelligence_source()
        if source is None:
            return None
        layer, file_path, page_index = source
        try:
            image_mtime = os.path.getmtime(file_path)
        except OSError:
            image_mtime = None
        ratio = self._scene_builder.get_coordinate_system().scale_ratio
        page = self._current_page
        return (
            page.uid,
            layer,
            file_path,
            image_mtime,
            page_index,
            float(self._pdf_width_pts or page.width_pts or 0.0),
            float(self._pdf_height_pts or page.height_pts or 0.0),
            page.overlay_rect,
            float(page.overlay_rotation),
            float(page.deskew_rotation_overlay),
            float(ratio),
        )

    def _pdf_raw_point_to_page_point(
        self,
        x: float,
        y: float,
        raw_width_pts: float,
        raw_height_pts: float,
        intrinsic_rotation: int,
    ) -> tuple[float, float]:
        rotation = int(intrinsic_rotation or 0) % 360
        if rotation == 90:
            return y, x
        if rotation == 180:
            return raw_width_pts - x, y
        if rotation == 270:
            return raw_height_pts - y, raw_width_pts - x
        return x, raw_height_pts - y

    def _pdf_intelligence_point_to_page_point(
        self,
        source_layer: str,
        x: float,
        y: float,
        source_width_pts: float,
        source_height_pts: float,
    ) -> tuple[float, float]:
        if source_layer != "overlay":
            return x, y
        page = self._current_page
        if page is None:
            return x, y
        if source_width_pts <= 0.0 or source_height_pts <= 0.0:
            return x, y
        rect_x, rect_y, rect_w, rect_h = page.overlay_rect_page_points()
        if rect_w <= 0.0 or rect_h <= 0.0:
            return x, y
        scale_x = rect_w / source_width_pts
        scale_y = rect_h / source_height_pts
        total_rotation = float(page.overlay_rotation + page.deskew_rotation_overlay)
        scaled_x = x * scale_x
        scaled_y = y * scale_y
        if abs(total_rotation) <= 1e-12:
            return rect_x + scaled_x, rect_y + scaled_y
        cos_a = math.cos(total_rotation)
        sin_a = math.sin(total_rotation)
        return (
            rect_x + scaled_x * cos_a - scaled_y * sin_a,
            rect_y + scaled_x * sin_a + scaled_y * cos_a,
        )

    def _build_takeoff_snap_segments(self) -> list:
        segments = []

        def add_polygon_segments(points: list[tuple[float, float]]) -> None:
            if len(points) < 2:
                return
            for i in range(len(points)):
                x1, y1 = points[i]
                x2, y2 = points[(i + 1) % len(points)]
                if math.hypot(x2 - x1, y2 - y1) < 1e-9:
                    continue
                segments.append((float(x1), float(y1), float(x2), float(y2)))

        def add_linear_border_segments(
            x1: float,
            y1: float,
            x2: float,
            y2: float,
            thickness_ost: float,
        ) -> None:
            dx = x2 - x1
            dy = y2 - y1
            length = math.hypot(dx, dy)
            if length < 1e-9:
                return
            half_thickness = float(thickness_ost) / 2.0
            if half_thickness <= 0.0:
                segments.append((x1, y1, x2, y2))
                return
            nx = -dy / length
            ny = dx / length
            ox = nx * half_thickness
            oy = ny * half_thickness
            segments.append((x1 + ox, y1 + oy, x2 + ox, y2 + oy))
            segments.append((x1 - ox, y1 - oy, x2 - ox, y2 - oy))

        def add_count_border_segments(takeoff, condition) -> None:
            if len(takeoff.position) < 2:
                return
            cx = float(takeoff.position[0])
            cy = float(takeoff.position[1])
            shape_id = condition.shape if condition.shape else shapes.SQUARE
            width_ost = max(condition.width if condition.width else 1.0, 1.0)
            if shape_id == shapes.SQUARE or shape_id == shapes.CIRCLE:
                depth_ost = width_ost
            else:
                depth_ost = max(condition.depth if condition.depth else width_ost, 1.0)
            if condition.is_count:
                scale = max(condition.display_size, 0.1) / 100.0
                width_ost *= scale
                depth_ost *= scale
            points = compute_count_vertices(
                cx,
                cy,
                shape_id,
                width_ost,
                depth_ost,
                takeoff.rotation,
            )
            add_polygon_segments(points)

        for takeoff in self._current_takeoffs.values():
            condition = self._current_conditions.get(takeoff.condition_uid)
            if not condition or not condition.layer_visible:
                continue
            pos = takeoff.position
            if condition.condition_type == Condition.TYPE_LINEAR:
                if condition.is_curved_segment or len(pos) < 4:
                    continue
                thickness_ost = float(
                    condition.thickness if condition.thickness else 1.0
                )
                usable_len = len(pos) - (len(pos) % 2)
                for i in range(0, usable_len - 2, 2):
                    add_linear_border_segments(
                        float(pos[i]),
                        float(pos[i + 1]),
                        float(pos[i + 2]),
                        float(pos[i + 3]),
                        thickness_ost,
                    )
            elif condition.condition_type == Condition.TYPE_AREA:
                if len(pos) < 6:
                    continue
                usable_len = len(pos) - (len(pos) % 2)
                points = [
                    (float(pos[i]), float(pos[i + 1])) for i in range(0, usable_len, 2)
                ]
                add_polygon_segments(points)
            elif condition.condition_type in (
                Condition.TYPE_COUNT,
                Condition.TYPE_ATTACHMENT,
            ):
                add_count_border_segments(takeoff, condition)
        return segments

    def _build_pdf_snap_segments(self) -> list:
        if not self._pdf_snap_available_for_current_page():
            return []
        cache_key = self._pdf_snap_cache_key()
        if cache_key is None:
            return []
        if cache_key == self._pdf_snap_segments_cache_key:
            return list(self._pdf_snap_segments_cache)
        page = self._current_page
        source_layer, file_path, page_index = self._pdf_intelligence_source()
        renderer = ost_pdf.PDFRenderer()
        try:
            with pdfium_lock:
                if not renderer.open(file_path):
                    logger.warning(
                        "Could not open PDF for snap vector extraction: %s",
                        file_path,
                    )
                    self._pdf_snap_segments_cache_key = cache_key
                    self._pdf_snap_segments_cache = []
                    return []
                raw_segments = renderer.extract_path_segments(page_index)
                page_info = renderer.page_info(page_index)
            page_width_pts = 0.0
            page_height_pts = 0.0
            if page_info is not None:
                page_width_pts = float(page_info.effective_width_pts)
                page_height_pts = float(page_info.effective_height_pts)
            if source_layer != "overlay":
                if page_width_pts <= 0.0:
                    page_width_pts = float(self._pdf_width_pts or page.width_pts or 0.0)
                if page_height_pts <= 0.0:
                    page_height_pts = float(
                        self._pdf_height_pts or page.height_pts or 0.0
                    )
            if page_width_pts <= 0.0 or page_height_pts <= 0.0:
                self._pdf_snap_segments_cache_key = cache_key
                self._pdf_snap_segments_cache = []
                return []
            intrinsic_rotation = 0
            raw_width_pts = page_width_pts
            raw_height_pts = page_height_pts
            if page_info is not None:
                intrinsic_rotation = int(page_info.intrinsic_rotation or 0)
                if page_info.crop_width_pts and page_info.crop_height_pts:
                    raw_width_pts = float(page_info.crop_width_pts)
                    raw_height_pts = float(page_info.crop_height_pts)
                elif page_info.media_width_pts and page_info.media_height_pts:
                    raw_width_pts = float(page_info.media_width_pts)
                    raw_height_pts = float(page_info.media_height_pts)
            ratio = self._scene_builder.get_coordinate_system().scale_ratio
            point_to_ost = ratio / 72.0
            segments = []
            for x1, y1, x2, y2 in raw_segments:
                px1, py1 = self._pdf_raw_point_to_page_point(
                    float(x1),
                    float(y1),
                    raw_width_pts,
                    raw_height_pts,
                    intrinsic_rotation,
                )
                px2, py2 = self._pdf_raw_point_to_page_point(
                    float(x2),
                    float(y2),
                    raw_width_pts,
                    raw_height_pts,
                    intrinsic_rotation,
                )
                px1, py1 = self._pdf_intelligence_point_to_page_point(
                    source_layer,
                    px1,
                    py1,
                    page_width_pts,
                    page_height_pts,
                )
                px2, py2 = self._pdf_intelligence_point_to_page_point(
                    source_layer,
                    px2,
                    py2,
                    page_width_pts,
                    page_height_pts,
                )
                segments.append(
                    (
                        px1 * point_to_ost,
                        py1 * point_to_ost,
                        px2 * point_to_ost,
                        py2 * point_to_ost,
                    )
                )
            self._pdf_snap_segments_cache_key = cache_key
            self._pdf_snap_segments_cache = list(segments)
            return segments
        except Exception:
            logger.exception("Failed to extract PDF snap vectors")
            self._pdf_snap_segments_cache_key = cache_key
            self._pdf_snap_segments_cache = []
            return []
        finally:
            with pdfium_lock:
                renderer.close()

    def _ensure_takeoff_snap_index(self) -> SnapIndex:
        if self._takeoff_snap_index is None:
            self._takeoff_snap_index = SnapIndex()
        if self._takeoff_snap_index_dirty:
            self._takeoff_snap_index.build(self._build_takeoff_snap_segments())
            self._takeoff_snap_index_dirty = False
        return self._takeoff_snap_index

    def _ensure_pdf_snap_index(self) -> SnapIndex:
        if self._pdf_snap_index is None:
            self._pdf_snap_index = SnapIndex()
        if self._pdf_snap_index_dirty and self._pdf_snap_available_for_current_page():
            self._pdf_snap_index.build(self._build_pdf_snap_segments())
            self._pdf_snap_index_dirty = False
        return self._pdf_snap_index

    def _request_place_preview_repaint(self) -> None:
        viewport = self.viewport()
        if viewport is not None:
            viewport.update()

    def refresh_place_preview_after_view_change(self) -> None:
        if self._last_mouse_vp_pos is not None and self._place_preview_items:
            if self._cursor_mode == "annotation_place":
                self.update_annotation_place_preview(
                    self.mapToScene(self._last_mouse_vp_pos)
                )
            else:
                self.update_place_preview(self.mapToScene(self._last_mouse_vp_pos))
        self._request_place_preview_repaint()

    def _should_update_place_preview(self, cond_type: int) -> bool:
        if cond_type in (
            Condition.TYPE_AREA,
            Condition.TYPE_COUNT,
            Condition.TYPE_ATTACHMENT,
        ):
            return True
        if cond_type == Condition.TYPE_LINEAR:
            return self._place_linear_dragging or not self._place_points
        return False

    def _screen_px_to_ost_radius(self, threshold_px: float) -> float:
        origin = self.mapToScene(QtCore.QPoint(0, 0))
        offset = self.mapToScene(QtCore.QPoint(int(threshold_px), 0))
        ost_origin = self._scene_pos_to_ost(origin)
        ost_offset = self._scene_pos_to_ost(offset)
        return math.hypot(
            ost_offset.x() - ost_origin.x(),
            ost_offset.y() - ost_origin.y(),
        )

    def _query_takeoff_snap(
        self, ost_x: float, ost_y: float, threshold_px: int
    ) -> tuple | None:
        if not self._snap_to_takeoffs_enabled or threshold_px <= 0:
            return None
        return self._ensure_takeoff_snap_index().query(
            float(ost_x),
            float(ost_y),
            float(self._screen_px_to_ost_radius(float(threshold_px))),
        )

    def _query_pdf_line_snap(
        self, ost_x: float, ost_y: float, threshold_px: int
    ) -> tuple | None:
        if (
            not self._snap_to_pdf_lines_enabled
            or threshold_px <= 0
            or not self._pdf_snap_available_for_current_page()
        ):
            return None
        return self._ensure_pdf_snap_index().query(
            float(ost_x),
            float(ost_y),
            float(self._screen_px_to_ost_radius(float(threshold_px))),
        )

    def _grid_snap_from_cursor(
        self, cursor_scene: QtCore.QPointF, cursor_ost: QtCore.QPointF
    ) -> tuple[float, float] | None:
        threshold_px = int(self._snap_to_grid_threshold_px)
        if (
            not self._snap_to_grid_enabled
            or threshold_px <= 0
            or self._snap_increments <= 0
        ):
            return None
        ost_x = self.snap_ost(cursor_ost.x())
        ost_y = self.snap_ost(cursor_ost.y())
        snapped_scene = self._ost_to_scene_pos(ost_x, ost_y)
        cursor_vp = self.mapFromScene(cursor_scene)
        snapped_vp = self.mapFromScene(snapped_scene)
        dist_px = math.hypot(
            snapped_vp.x() - cursor_vp.x(),
            snapped_vp.y() - cursor_vp.y(),
        )
        if dist_px > threshold_px:
            return None
        return ost_x, ost_y

    def _placement_snap_from_scene(self, cursor_scene: QtCore.QPointF):
        cs = self._scene_builder.get_coordinate_system()
        ost_factor = cs.scale_ratio / (72.0 * cs.view_scale)
        inv_factor = 1.0 / ost_factor
        cursor_ost = self._scene_pos_to_ost(cursor_scene)
        hit = self._query_takeoff_snap(
            float(cursor_ost.x()),
            float(cursor_ost.y()),
            int(self._snap_to_takeoffs_threshold_px),
        )
        if hit is None:
            hit = self._query_pdf_line_snap(
                float(cursor_ost.x()),
                float(cursor_ost.y()),
                int(self._snap_to_pdf_lines_threshold_px),
            )
        if hit is not None:
            ost_x, ost_y, kind, _segment_index = hit
            return (
                float(ost_x),
                float(ost_y),
                float(ost_x) * inv_factor,
                float(ost_y) * inv_factor,
                int(kind),
            )
        grid_snap = self._grid_snap_from_cursor(cursor_scene, cursor_ost)
        if grid_snap is not None:
            ost_x, ost_y = grid_snap
            return ost_x, ost_y, ost_x * inv_factor, ost_y * inv_factor, GRID
        ost_x = float(cursor_ost.x())
        ost_y = float(cursor_ost.y())
        return ost_x, ost_y, ost_x * inv_factor, ost_y * inv_factor, NONE

    def _is_line_snap(self, snap_kind: int) -> bool:
        return snap_kind in (ENDPOINT, MIDPOINT, PERPENDICULAR)

    def _add_place_handle(self, x: float, y: float, half: float = 4.0) -> None:
        marker = QGraphicsRectItem(-half, -half, half * 2, half * 2)
        background_color = self._current_handle_background_color()
        apply_takeoff_handle_style(marker, background_color)
        marker.setZValue(15)
        marker.setPos(self._pt_to_scene(x, y))
        marker.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self._scene.addItem(marker)
        self._place_preview_items.append(marker)

    def _add_snap_cursor_marker(self, x: float, y: float, snap_kind: int) -> None:
        if self._is_line_snap(snap_kind):
            self._add_place_handle(x, y)

    def _add_preview_item(self, item, page_transform=None, target_list=None) -> None:
        if page_transform is not None:
            item.setTransform(page_transform)
        self._scene.addItem(item)
        (target_list if target_list is not None else self._place_preview_items).append(
            item
        )

    def _add_dashed_path_preview(
        self,
        path: QPainterPath,
        color: QColor,
        z_value: float,
        page_transform=None,
        target_list=None,
        pen_width: float = 1.0,
    ) -> None:
        dash_pen = QPen(color)
        dash_pen.setWidthF(pen_width)
        dash_pen.setStyle(Qt.PenStyle.DashLine)
        dash_pen.setCosmetic(True)
        item = QGraphicsPathItem()
        item.setPath(path)
        item.setPen(dash_pen)
        item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        item.setZValue(z_value)
        self._add_preview_item(item, page_transform, target_list)

    def clear_place_preview(self) -> None:
        if not self._place_preview_items and not self._backout_orig_parent_path:
            self._place_flashing = False
            return
        self._place_flashing = False
        if self._backout_orig_parent_path:
            parent_items = self._uid_to_items.get(self._backout_parent_uid, [])
            for item in parent_items:
                if isinstance(item, QGraphicsPathItem):
                    item.setPath(self._backout_orig_parent_path)
                    break
            self._backout_orig_parent_path = None
        for item in self._place_preview_items:
            try:
                self._scene.removeItem(item)
            except (TypeError, RuntimeError):
                pass
        self._place_preview_items.clear()

    def _enter_annotation_place_mode(self, annotation_type: str) -> bool:
        if annotation_type not in PLACEABLE_ANNOTATION_TYPES:
            return False
        self.clear_place_preview()
        if annotation_type not in _POINT_ANNOTATION_TYPES:
            self._point_annotation_release_pending = False
        self._annotation_place_type = annotation_type
        self._annotation_place_points = []
        self._annotation_place_dragging = False
        self._annotation_area_rect_dragging = False
        return True

    def _exit_annotation_place_mode(self) -> None:
        self.clear_place_preview()
        self._point_annotation_release_pending = False
        self._annotation_place_type = None
        self._annotation_place_points = []
        self._annotation_place_dragging = False
        self._annotation_area_rect_dragging = False

    def _drag_annotation_placement_position(
        self, cursor_scene: QtCore.QPointF
    ) -> tuple[list, int]:
        ost_x, ost_y, _cx, _cy, snap_kind = self._placement_snap_from_scene(
            cursor_scene
        )
        x1, y1 = self._annotation_place_points[0]
        if self._annotation_place_type in ("dimension", "line", "arrow"):
            x2, y2 = self._snap_angle_for_placement(x1, y1, ost_x, ost_y, snap_kind)
        else:
            x2, y2 = ost_x, ost_y
        return [x1, y1, x2, y2], snap_kind

    def _text_position_from_drag_corners(self, position: list) -> list:
        x1, y1, x2, y2 = position[:4]
        return [
            (x1 + x2) / 2.0,
            (y1 + y2) / 2.0,
            abs(x2 - x1),
            abs(y2 - y1),
        ]

    def _annotation_preview_style(self) -> tuple[QColor, float]:
        color_hex, width = annotation_default_style(self._annotation_place_type)
        return QColor(color_hex), width

    def _add_linear_annotation_preview(
        self,
        annotation_type: str,
        position: list,
        color: QColor,
        width: float,
        page_transform,
    ) -> None:
        cs = self._scene_builder.get_coordinate_system()
        tx = cs.transform_vertices_to_2d(position)
        if len(tx) < 4:
            return
        x1, y1, x2, y2 = tx[:4]
        path = QPainterPath()
        path.moveTo(x1, y1)
        path.lineTo(x2, y2)
        if annotation_type == "arrow":
            arrow_size = max(width * 20.0, 24.0)
            angle = math.atan2(y2 - y1, x2 - x1)
            arrow_angle = math.radians(30.0)
            left_x = x2 - arrow_size * math.cos(angle - arrow_angle)
            left_y = y2 - arrow_size * math.sin(angle - arrow_angle)
            right_x = x2 - arrow_size * math.cos(angle + arrow_angle)
            right_y = y2 - arrow_size * math.sin(angle + arrow_angle)
            path.moveTo(left_x, left_y)
            path.lineTo(x2, y2)
            path.lineTo(right_x, right_y)
        self._add_annotation_path_preview(path, color, width, page_transform)

    def _add_box_annotation_preview(
        self,
        annotation_type: str,
        position: list,
        color: QColor,
        width: float,
        page_transform,
    ) -> None:
        cs = self._scene_builder.get_coordinate_system()
        tx = cs.transform_vertices_to_2d(position)
        if len(tx) < 4:
            return
        x1, y1, x2, y2 = tx[:4]
        rect = QtCore.QRectF(
            min(x1, x2),
            min(y1, y2),
            abs(x2 - x1),
            abs(y2 - y1),
        )
        path = QPainterPath()
        if annotation_type == "oval":
            path.addEllipse(rect)
        else:
            path.addRect(rect)
        if annotation_type == "text":
            self._add_dashed_path_preview(
                path,
                _TEXT_SELECTION_OUTLINE_COLOR,
                15,
                page_transform,
                pen_width=2.0,
            )
            return
        if annotation_type == "namedview":
            self._add_annotation_path_preview(
                path,
                color,
                2.0,
                page_transform,
            )
            return
        if annotation_type == "highlight":
            item = QGraphicsPathItem()
            item.setPath(path)
            highlight_color = QColor(color)
            highlight_color.setAlphaF(0.3)
            item.setPen(QPen(Qt.PenStyle.NoPen))
            item.setBrush(QBrush(highlight_color))
            item.setZValue(15)
            self._add_preview_item(item, page_transform)
            return
        self._add_annotation_path_preview(path, color, width, page_transform)

    def _add_area_annotation_preview(
        self,
        annotation_type: str,
        points: list[tuple[float, float]],
        color: QColor,
        width: float,
        page_transform,
    ) -> None:
        if len(points) < 2:
            return
        cs = self._scene_builder.get_coordinate_system()
        flat_ost = [v for point in points for v in point]
        flat_scene = cs.transform_vertices_to_2d(flat_ost)
        scene_points = [
            (flat_scene[i], flat_scene[i + 1]) for i in range(0, len(flat_scene) - 1, 2)
        ]
        if len(scene_points) < 2:
            return
        path = QPainterPath()
        if annotation_type == "cloud" and len(scene_points) >= 3:
            segments = create_cloud_path_points(scene_points)
            for idx, (_start, cp1, cp2, end) in enumerate(segments):
                if idx == 0:
                    path.moveTo(scene_points[0][0], scene_points[0][1])
                path.cubicTo(cp1[0], cp1[1], cp2[0], cp2[1], end[0], end[1])
            path.closeSubpath()
        else:
            path.moveTo(scene_points[0][0], scene_points[0][1])
            for x, y in scene_points[1:]:
                path.lineTo(x, y)
            if len(scene_points) >= 3:
                path.closeSubpath()
        self._add_annotation_path_preview(path, color, width, page_transform)
        for hx, hy in scene_points:
            self._add_place_handle(hx, hy)

    def _add_ink_annotation_preview(
        self,
        points: list[tuple[float, float]],
        color: QColor,
        width: float,
        page_transform,
    ) -> None:
        if len(points) < 2:
            return
        cs = self._scene_builder.get_coordinate_system()
        flat_ost = [v for point in points for v in point]
        flat_scene = cs.transform_vertices_to_2d(flat_ost)
        if len(flat_scene) < 4:
            return
        path = QPainterPath()
        path.moveTo(flat_scene[0], flat_scene[1])
        for i in range(2, len(flat_scene) - 1, 2):
            path.lineTo(flat_scene[i], flat_scene[i + 1])
        self._add_annotation_path_preview(path, color, width, page_transform)

    def _add_annotation_path_preview(
        self, path: QPainterPath, color: QColor, width: float, page_transform
    ) -> None:
        if path.isEmpty():
            return
        item = QGraphicsPathItem()
        item.setPath(path)
        pen = QPen(color)
        pen.setWidthF(width)
        pen.setCosmetic(True)
        item.setPen(pen)
        item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        item.setZValue(15)
        self._add_preview_item(item, page_transform)

    def update_annotation_place_preview(self, cursor_scene: QtCore.QPointF) -> None:
        self.clear_place_preview()
        if self._annotation_place_type not in PLACEABLE_ANNOTATION_TYPES:
            return
        if not self._annotation_place_points:
            _ost_x, _ost_y, cx, cy, snap_kind = self._placement_snap_from_scene(
                cursor_scene
            )
            self._add_snap_cursor_marker(cx, cy, snap_kind)
            self._request_place_preview_repaint()
            return
        page_transform = self._current_page_transform()
        annotation_type = self._annotation_place_type
        if annotation_type in _DRAG_ANNOTATION_TYPES:
            position, _snap_kind = self._drag_annotation_placement_position(
                cursor_scene
            )
            if math.hypot(position[2] - position[0], position[3] - position[1]) <= 1e-9:
                return
            if annotation_type == "dimension":
                color_hex, width = annotation_default_style("dimension")
                annotation = BidAnnotation(
                    uid="__dimension_preview__",
                    annotation_type="dimension",
                    page_uid=self._current_bid_page_uid or "",
                    position=position,
                    color=color_hex,
                    width=width,
                    properties=dimension_annotation_properties(),
                )
                cs = self._scene_builder.get_coordinate_system()
                dimension = calculate_dimension_geometry(
                    annotation, position, cs.transform_vertices_to_2d
                )
                if not dimension:
                    return
                path = build_dimension_path(dimension, cs)
                self._add_annotation_path_preview(
                    path, QColor(annotation.color), annotation.width, page_transform
                )
                text_item = create_dimension_text_item(
                    dimension,
                    annotation.color,
                    cs,
                    DIMENSION_FONT_SIZE_ADJUSTMENT,
                )
                if text_item is not None:
                    text_item.setZValue(16)
                    self._add_preview_item(text_item, page_transform)
            elif annotation_type in ("line", "arrow"):
                color, width = self._annotation_preview_style()
                self._add_linear_annotation_preview(
                    annotation_type, position, color, width, page_transform
                )
            else:
                color, width = self._annotation_preview_style()
                self._add_box_annotation_preview(
                    annotation_type, position, color, width, page_transform
                )
        elif annotation_type in _INK_ANNOTATION_TYPES:
            color, width = self._annotation_preview_style()
            self._append_ink_annotation_point(cursor_scene)
            self._add_ink_annotation_preview(
                self._annotation_place_points, color, width, page_transform
            )
        else:
            color, width = self._annotation_preview_style()
            ost_x, ost_y, _cx, _cy, snap_kind = self._placement_snap_from_scene(
                cursor_scene
            )
            if self._annotation_area_rect_dragging:
                x1, y1 = self._annotation_place_points[0]
                position = self._rectangle_position_from_corners(x1, y1, ost_x, ost_y)
                points = self._points_from_position(position)
                self._add_area_annotation_preview(
                    annotation_type, points, color, width, page_transform
                )
                self._request_place_preview_repaint()
                return
            last_x, last_y = self._annotation_place_points[-1]
            end_x, end_y = self._snap_angle_for_placement(
                last_x, last_y, ost_x, ost_y, snap_kind
            )
            points = self._annotation_place_points + [(end_x, end_y)]
            self._add_area_annotation_preview(
                annotation_type, points, color, width, page_transform
            )
        self._request_place_preview_repaint()

    def handle_annotation_place_press(self, event) -> bool:
        if self._annotation_place_type not in PLACEABLE_ANNOTATION_TYPES:
            return False
        scene_pos = self.mapToScene(event.pos())
        if self._annotation_place_type in _POINT_ANNOTATION_TYPES:
            ost_x, ost_y, _cx, _cy, _snap_kind = self._placement_snap_from_scene(
                scene_pos
            )
            page_uid = self._current_bid_page_uid or ""
            if not page_uid:
                return False
            self._selected_uids.clear()
            self.update_selection_visuals()
            self.clear_place_preview()
            self._point_annotation_release_pending = True
            self.hotlink_placement_requested.emit([ost_x, ost_y], page_uid)
            event.accept()
            return True
        if self._annotation_place_type in _DRAG_ANNOTATION_TYPES:
            if self._annotation_place_points and not self._annotation_place_dragging:
                position, _snap_kind = self._drag_annotation_placement_position(
                    scene_pos
                )
                if self._commit_annotation_placement(
                    self._annotation_place_type, position
                ):
                    event.accept()
                    return True
                self.update_annotation_place_preview(scene_pos)
                event.accept()
                return True
            ost_x, ost_y, _cx, _cy, _snap_kind = self._placement_snap_from_scene(
                scene_pos
            )
            self._selected_uids.clear()
            self.update_selection_visuals()
            self._annotation_place_points = [(ost_x, ost_y)]
            self._annotation_place_dragging = True
            self.update_annotation_place_preview(scene_pos)
            event.accept()
            return True
        if self._annotation_place_type in _INK_ANNOTATION_TYPES:
            point = self._ink_annotation_point_from_scene(scene_pos)
            self._selected_uids.clear()
            self.update_selection_visuals()
            self._annotation_place_points = [point]
            self._annotation_place_dragging = True
            self.update_annotation_place_preview(scene_pos)
            event.accept()
            return True
        ost_x, ost_y, _cx, _cy, snap_kind = self._placement_snap_from_scene(scene_pos)
        if self._annotation_area_rect_dragging:
            self._annotation_area_rect_dragging = False
        if not self._annotation_place_points:
            self._selected_uids.clear()
            self.update_selection_visuals()
            self._annotation_place_points = [(ost_x, ost_y)]
            self._annotation_area_rect_dragging = True
            self.update_annotation_place_preview(scene_pos)
            event.accept()
            return True
        if self._is_annotation_close_to_first(scene_pos):
            position = [v for point in self._annotation_place_points for v in point]
            self._commit_annotation_placement(self._annotation_place_type, position)
            event.accept()
            return True
        last_x, last_y = self._annotation_place_points[-1]
        ost_x, ost_y = self._snap_angle_for_placement(
            last_x, last_y, ost_x, ost_y, snap_kind
        )
        candidate = self._annotation_place_points + [(ost_x, ost_y)]
        if len(candidate) < 4 or not polyline_self_intersects(candidate):
            self._annotation_place_points.append((ost_x, ost_y))
        self.update_annotation_place_preview(scene_pos)
        event.accept()
        return True

    def handle_annotation_place_release(self, event) -> bool:
        if self._point_annotation_release_pending:
            self._point_annotation_release_pending = False
            event.accept()
            return True
        if (
            self._annotation_place_type not in PLACEABLE_ANNOTATION_TYPES
            or not self._annotation_place_points
        ):
            return False
        if self._annotation_place_type in _AREA_ANNOTATION_TYPES:
            if self._annotation_area_rect_dragging:
                scene_pos = self.mapToScene(event.pos())
                ost_x2, ost_y2, _cx, _cy, _snap_kind = self._placement_snap_from_scene(
                    scene_pos
                )
                x1, y1 = self._annotation_place_points[0]
                min_len = self._snap_increments if self._snap_increments > 0 else 1e-6
                self._annotation_area_rect_dragging = False
                if abs(ost_x2 - x1) >= min_len and abs(ost_y2 - y1) >= min_len:
                    position = self._rectangle_position_from_corners(
                        x1, y1, ost_x2, ost_y2
                    )
                    if self._commit_annotation_placement(
                        self._annotation_place_type, position
                    ):
                        event.accept()
                        return True
                self.update_annotation_place_preview(scene_pos)
            event.accept()
            return True
        if self._annotation_place_type in _INK_ANNOTATION_TYPES:
            if not self._annotation_place_dragging:
                return False
            scene_pos = self.mapToScene(event.pos())
            self._append_ink_annotation_point(scene_pos)
            position = [v for point in self._annotation_place_points for v in point]
            if self._commit_annotation_placement(self._annotation_place_type, position):
                event.accept()
                return True
            self._annotation_place_dragging = False
            self._annotation_place_points = []
            self.clear_place_preview()
            event.accept()
            return True
        if not self._annotation_place_dragging:
            return False
        scene_pos = self.mapToScene(event.pos())
        position, _snap_kind = self._drag_annotation_placement_position(scene_pos)
        if self._commit_annotation_placement(self._annotation_place_type, position):
            event.accept()
            return True
        self._annotation_place_dragging = False
        self._annotation_place_points = []
        self.clear_place_preview()
        self.update_annotation_place_preview(scene_pos)
        event.accept()
        return True

    def _is_annotation_close_to_first(self, scene_pos: QtCore.QPointF) -> bool:
        if len(self._annotation_place_points) < 3:
            return False
        first_x, first_y = self._annotation_place_points[0]
        first_scene = self._ost_to_scene_pos(first_x, first_y)
        first_vp = self.mapFromScene(first_scene)
        current_vp = self.mapFromScene(scene_pos)
        dx = current_vp.x() - first_vp.x()
        dy = current_vp.y() - first_vp.y()
        return math.hypot(dx, dy) <= 12.0

    def _ink_annotation_point_from_scene(
        self, scene_pos: QtCore.QPointF
    ) -> tuple[float, float]:
        point = self._scene_pos_to_ost(scene_pos)
        return float(point.x()), float(point.y())

    def _append_ink_annotation_point(self, scene_pos: QtCore.QPointF) -> None:
        point = self._ink_annotation_point_from_scene(scene_pos)
        if not self._annotation_place_points:
            self._annotation_place_points.append(point)
            return
        last_x, last_y = self._annotation_place_points[-1]
        if math.hypot(point[0] - last_x, point[1] - last_y) > 1e-9:
            self._annotation_place_points.append(point)

    def _commit_annotation_placement(
        self, annotation_type: str, position: list
    ) -> bool:
        min_len = self._snap_increments if self._snap_increments > 0 else 1e-6
        if annotation_type in _DRAG_ANNOTATION_TYPES:
            distance = math.hypot(position[2] - position[0], position[3] - position[1])
            if distance < min_len:
                return False
            if annotation_type in (
                "rect",
                "oval",
                "text",
                "highlight",
                "namedview",
            ) and (
                abs(position[2] - position[0]) < min_len
                or abs(position[3] - position[1]) < min_len
            ):
                return False
            if annotation_type == "text":
                position = self._text_position_from_drag_corners(position)
            elif annotation_type == "namedview":
                position = named_view_position_from_bounds(*position[:4])
        elif annotation_type in _INK_ANNOTATION_TYPES:
            points = self._points_from_position(position)
            if len(points) < 2:
                return False
            distance = sum(
                math.hypot(bx - ax, by - ay)
                for (ax, ay), (bx, by) in zip(points, points[1:])
            )
            if distance < min_len:
                return False
        elif annotation_type in _AREA_ANNOTATION_TYPES:
            points = self._points_from_position(position)
            if len(points) < 3 or not polygon_is_valid(points):
                return False
        else:
            return False
        page_uid = self._current_bid_page_uid or ""
        if not page_uid:
            return False
        self.clear_place_preview()
        self._annotation_place_points = []
        self._annotation_place_dragging = False
        self._annotation_area_rect_dragging = False
        if annotation_type == "text":
            return bool(self.begin_text_annotation_draft(position, page_uid))
        if annotation_type == "namedview":
            return bool(self.begin_named_view_draft(position, page_uid))
        self.annotation_created.emit(annotation_type, position, page_uid)
        return True

    def _flash_invalid_preview(self, condition_color: QColor) -> None:
        if self._place_flashing:
            return
        self._place_flashing = True
        red = QColor(200, 0, 0)
        fill_item = next(
            (
                it
                for it in self._place_preview_items
                if isinstance(it, QGraphicsPathItem)
                and it.brush().style() != Qt.BrushStyle.NoBrush
            ),
            None,
        )
        if fill_item is None:
            self._place_flashing = False
            return
        fill_item.setPen(QPen(condition_color))
        fill_item.setBrush(QBrush(condition_color))
        weak_self = weakref.ref(self)
        weak_item = weakref.ref(fill_item)

        def _restore() -> None:
            view = weak_self()
            item = weak_item()
            if view is None or item is None:
                return
            if not view._place_flashing:
                return
            item.setPen(QPen(red))
            item.setBrush(QBrush(red))
            view._place_flashing = False

        QtCore.QTimer.singleShot(220, _restore)

    def _condition_preview_color_and_opacity(
        self, condition_uid: str, condition: Condition, default_opacity: float = 1.0
    ) -> tuple[str, float]:
        color_entry = self._current_color_map.get(condition_uid)
        if color_entry is not None:
            return self._color_service.as_hex_with_opacity(color_entry)
        color_hex = (
            self._color_service.int_to_hex(condition.color_fill)
            if condition.color_fill
            else "#808080"
        )
        return color_hex, default_opacity

    def update_place_preview(self, cursor_scene: QtCore.QPointF) -> None:
        self.clear_place_preview()
        cs = self._scene_builder.get_coordinate_system()
        active_uid = self._backout_active_uid or self._place_session_uid
        condition = self._current_conditions.get(active_uid)
        if not condition:
            return
        color_hex, base_opacity = self._condition_preview_color_and_opacity(
            active_uid, condition
        )
        preview_opacity = base_opacity
        qcolor = QColor(color_hex)
        cond_type = condition.condition_type
        pts = self._place_points
        ost_x, ost_y, cx, cy, snap_kind = self._placement_snap_from_scene(cursor_scene)
        page_transform = self._current_page_transform()
        if cond_type == Condition.TYPE_LINEAR:
            if not (self._place_linear_dragging and pts):
                self._add_snap_cursor_marker(cx, cy, snap_kind)
                self._request_place_preview_repaint()
                return
            tx = cs.transform_vertices_to_2d([pts[0][0], pts[0][1]])
            x1, y1 = tx[0], tx[1]
            x2, y2 = self._snap_angle_for_placement(x1, y1, cx, cy, snap_kind)
            path = self._build_linear_path(cs, condition, x1, y1, x2, y2)
            if path.isEmpty():
                return
            item = QGraphicsPathItem()
            item.setPath(path)
            pattern_angle = compute_line_angle(x1, y1, x2, y2)
            self._apply_pattern_preview(
                item,
                path,
                condition,
                qcolor,
                preview_opacity,
                page_transform,
                pattern_angle,
            )
            self._add_secondary_condition_previews(
                path,
                page_transform,
                preview_opacity,
                linear_endpoints=(x1, y1, x2, y2),
            )
            handle_pts = [(x1, y1), (x2, y2)]
            if condition.is_curved_segment:
                handle_pts.append(((x1 + x2) / 2.0, (y1 + y2) / 2.0))
            for hx, hy in handle_pts:
                self._add_place_handle(hx, hy)
            self._request_place_preview_repaint()
        elif cond_type == Condition.TYPE_AREA:
            if not pts:
                self._add_snap_cursor_marker(cx, cy, snap_kind)
                self._request_place_preview_repaint()
                return
            if self._place_area_rect_dragging:
                x1, y1 = pts[0]
                flat_s = cs.transform_vertices_to_2d([x1, y1])
                sx1, sy1 = flat_s[0], flat_s[1]
                if self._backout_parent_uid:
                    ost_x2 = ost_x
                    ost_y2 = ost_y
                    corners = [(x1, y1), (ost_x2, y1), (ost_x2, ost_y2), (x1, ost_y2)]
                    pos_flat = self._rectangle_position_from_corners(
                        x1, y1, ost_x2, ost_y2
                    )
                    all_inside = all(
                        self.is_inside_parent(px, py) for px, py in corners
                    )
                    if all_inside and not self._check_hole_overlap(pos_flat):
                        self._backout_last_valid_ost = (ost_x2, ost_y2)
                    if self._backout_last_valid_ost:
                        valid_tx = cs.transform_vertices_to_2d(
                            list(self._backout_last_valid_ost)
                        )
                        cx, cy = valid_tx[0], valid_tx[1]
                rect_path = QPainterPath()
                rect_path.addRect(
                    min(sx1, cx), min(sy1, cy), abs(cx - sx1), abs(cy - sy1)
                )
                if self._backout_parent_uid:
                    self._update_parent_hole_preview(rect_path)
                else:
                    item = QGraphicsPathItem()
                    item.setPath(rect_path)
                    self._apply_pattern_preview(
                        item,
                        rect_path,
                        condition,
                        qcolor,
                        preview_opacity,
                        page_transform,
                    )
                    self._add_secondary_condition_previews(
                        rect_path, page_transform, preview_opacity
                    )
                self._add_dashed_path_preview(
                    rect_path, QColor(0, 0, 0), 11, page_transform
                )
                x_min, x_max = min(sx1, cx), max(sx1, cx)
                y_min, y_max = min(sy1, cy), max(sy1, cy)
                mx, my = (x_min + x_max) / 2, (y_min + y_max) / 2
                corner_pts = [
                    (x_min, y_min),
                    (x_max, y_min),
                    (x_max, y_max),
                    (x_min, y_max),
                ]
                mid_pts = [(mx, y_min), (x_max, my), (mx, y_max), (x_min, my)]
                for hx, hy in corner_pts:
                    self._add_place_handle(hx, hy)
                for hx, hy in mid_pts:
                    self._add_place_handle(hx, hy, 2.5)
                self._request_place_preview_repaint()
                return
            flat_ost = [v for pt in pts for v in pt]
            flat_scene = cs.transform_vertices_to_2d(flat_ost)
            scene_pts = [
                (flat_scene[i], flat_scene[i + 1]) for i in range(0, len(flat_scene), 2)
            ]
            last_sx, last_sy = scene_pts[-1]
            last_ost_x, last_ost_y = pts[-1]
            endpoint = self._area_final_endpoint_for_placement(
                last_ost_x, last_ost_y, ost_x, ost_y, snap_kind
            )
            snapped_scene = cs.transform_vertices_to_2d(
                [endpoint.final_x, endpoint.final_y]
            )
            snapped_end = (snapped_scene[0], snapped_scene[1])
            polyline_pts = scene_pts + [snapped_end]
            is_invalid = polyline_self_intersects(polyline_pts)
            fill_color = QColor(200, 0, 0) if is_invalid else qcolor
            path = QPainterPath()
            path.moveTo(scene_pts[0][0], scene_pts[0][1])
            for sx, sy in scene_pts[1:]:
                path.lineTo(sx, sy)
            path.lineTo(snapped_end[0], snapped_end[1])
            if self._backout_parent_uid and not is_invalid:
                self._update_parent_hole_preview(path)
            elif is_invalid:
                item = QGraphicsPathItem()
                item.setPath(path)
                item.setPen(QPen(fill_color))
                item.setBrush(QBrush(fill_color))
                item.setOpacity(preview_opacity)
                item.setZValue(10)
                self._add_preview_item(item, page_transform)
            else:
                item = QGraphicsPathItem()
                item.setPath(path)
                self._apply_pattern_preview(
                    item,
                    path,
                    condition,
                    qcolor,
                    preview_opacity,
                    page_transform,
                )
                if not self._backout_parent_uid:
                    self._add_secondary_condition_previews(
                        path, page_transform, preview_opacity
                    )
            self._add_dashed_path_preview(path, QColor(0, 0, 0), 11, page_transform)
            if endpoint.right_angle_indicator_active:
                indicator_pen = QPen(QColor("#1f9d45"))
                indicator_pen.setWidthF(2.0)
                indicator_pen.setCosmetic(True)
                indicator = QGraphicsLineItem(
                    last_sx,
                    last_sy,
                    snapped_end[0],
                    snapped_end[1],
                )
                indicator.setPen(indicator_pen)
                indicator.setZValue(12)
                self._add_preview_item(indicator, page_transform)
            for hx, hy in scene_pts:
                self._add_place_handle(hx, hy)
            self._add_place_handle(snapped_end[0], snapped_end[1])
            for i in range(len(polyline_pts) - 1):
                ax, ay = polyline_pts[i]
                bx, by = polyline_pts[i + 1]
                mx, my = (ax + bx) / 2, (ay + by) / 2
                self._add_place_handle(mx, my, 2.5)
            self._request_place_preview_repaint()
        elif cond_type in (Condition.TYPE_COUNT, Condition.TYPE_ATTACHMENT):
            self._add_snap_cursor_marker(cx, cy, snap_kind)
            self._request_place_preview_repaint()

    def handle_place_press(self, event) -> None:
        if self._place_flashing:
            event.accept()
            return
        scene_pos = self.mapToScene(event.pos())
        ost_x, ost_y, _cx, _cy, snap_kind = self._placement_snap_from_scene(scene_pos)
        cs = self._scene_builder.get_coordinate_system()
        active_uid = self._backout_active_uid or self._place_session_uid
        condition = self._current_conditions.get(active_uid)
        if not condition or not condition.layer_visible:
            event.accept()
            return
        cond_type = condition.condition_type
        if cond_type == Condition.TYPE_ATTACHMENT:
            parent_uid = self._find_area_at(ost_x, ost_y)
            if not parent_uid:
                event.accept()
                return
            self._selected_uids.clear()
            self.update_selection_visuals()
            self._invalidate_snap_index()
            self.hole_created.emit(
                self._place_session_uid,
                [ost_x, ost_y],
                self._current_bid_page_uid or "",
                parent_uid,
            )
        elif cond_type == Condition.TYPE_COUNT:
            self._selected_uids.clear()
            self.update_selection_visuals()
            self._invalidate_snap_index()
            self.takeoff_created.emit(
                self._place_session_uid,
                [ost_x, ost_y],
                self._current_bid_page_uid or "",
            )
        elif cond_type == Condition.TYPE_LINEAR:
            self._selected_uids.clear()
            self.update_selection_visuals()
            self._place_points = [(ost_x, ost_y)]
            self._place_linear_dragging = True
            self.update_place_preview(scene_pos)
        elif cond_type == Condition.TYPE_AREA:
            if not self._place_points:
                if self._backout_parent_uid:
                    if self._point_in_sibling_hole(ost_x, ost_y):
                        event.accept()
                        return
                    if not self.is_inside_parent(ost_x, ost_y):
                        event.accept()
                        return
                if not self._backout_parent_uid:
                    self._selected_uids.clear()
                    self.update_selection_visuals()
                    if self._place_session_uid is None:
                        event.accept()
                        return
                self._place_points = [(ost_x, ost_y)]
                self._place_area_rect_dragging = True
                self._set_area_placement_in_progress(True)
            else:
                first_ost_x, first_ost_y = self._place_points[0]
                factor = cs.scale_ratio / (72.0 * cs.view_scale)
                first_scene = self._pt_to_scene(
                    first_ost_x / factor, first_ost_y / factor
                )
                first_vp = self.mapFromScene(first_scene)
                cur_vp = event.position().toPoint()
                dist = (
                    (cur_vp.x() - first_vp.x()) ** 2 + (cur_vp.y() - first_vp.y()) ** 2
                ) ** 0.5
                if dist <= 12 and len(self._place_points) >= 3:
                    if polygon_is_valid(self._place_points):
                        pos_flat = [v for pt in self._place_points for v in pt]
                        if self._backout_parent_uid:
                            if not self._check_hole_overlap(pos_flat):
                                self._finish_area_placement_preview_state()
                                self.hole_created.emit(
                                    self._backout_active_uid,
                                    pos_flat,
                                    self._current_bid_page_uid or "",
                                    self._backout_parent_uid,
                                )
                        else:
                            self._finish_area_placement_preview_state()
                            self.takeoff_created.emit(
                                self._place_session_uid,
                                pos_flat,
                                self._current_bid_page_uid or "",
                            )
                else:
                    last_ox, last_oy = self._place_points[-1]
                    endpoint = self._area_final_endpoint_for_placement(
                        last_ox, last_oy, ost_x, ost_y, snap_kind
                    )
                    ost_x, ost_y = endpoint.final_x, endpoint.final_y
                    candidate = self._place_points + [(ost_x, ost_y)]
                    if polyline_self_intersects(candidate):
                        flash_hex, _ = self._condition_preview_color_and_opacity(
                            active_uid, condition
                        )
                        self._flash_invalid_preview(QColor(flash_hex))
                    elif not self._backout_parent_uid or (
                        self.is_inside_parent(ost_x, ost_y)
                        and not self._point_in_sibling_hole(ost_x, ost_y)
                    ):
                        self._place_points.append((ost_x, ost_y))
                        self.update_place_preview(scene_pos)
        event.accept()

    def handle_place_release_area(self, event) -> bool:
        condition = self._current_conditions.get(
            self._backout_active_uid or self._place_session_uid
        )
        if not (
            condition is not None
            and condition.layer_visible
            and condition.condition_type == Condition.TYPE_AREA
            and self._place_area_rect_dragging
            and self._place_points
        ):
            return False
        scene_pos = self.mapToScene(event.pos())
        ost_x2, ost_y2, _cx, _cy, _snap_kind = self._placement_snap_from_scene(
            scene_pos
        )
        x1, y1 = self._place_points[0]
        min_len = self._snap_increments if self._snap_increments > 0 else 1e-6
        self._place_area_rect_dragging = False
        if self._backout_parent_uid:
            use_valid = abs(ost_x2 - x1) < min_len or abs(ost_y2 - y1) < min_len
            if not use_valid:
                corners = [(x1, y1), (ost_x2, y1), (ost_x2, ost_y2), (x1, ost_y2)]
                pos = self._rectangle_position_from_corners(x1, y1, ost_x2, ost_y2)
                use_valid = not all(
                    self.is_inside_parent(px, py) for px, py in corners
                ) or self._check_hole_overlap(pos)
            if use_valid and self._backout_last_valid_ost:
                ost_x2, ost_y2 = self._backout_last_valid_ost
            elif use_valid:
                self.update_place_preview(scene_pos)
                self._backout_last_valid_ost = None
                event.accept()
                return True
            x2, y2 = ost_x2, ost_y2
            pos = self._rectangle_position_from_corners(x1, y1, x2, y2)
            self.clear_place_preview()
            self._place_points = []
            self._backout_last_valid_ost = None
            self._set_area_placement_in_progress(False)
            self._invalidate_snap_index()
            self.hole_created.emit(
                self._backout_active_uid,
                pos,
                self._current_bid_page_uid or "",
                self._backout_parent_uid,
            )
        elif abs(ost_x2 - x1) >= min_len and abs(ost_y2 - y1) >= min_len:
            pos = self._rectangle_position_from_corners(x1, y1, ost_x2, ost_y2)
            self._finish_area_placement_preview_state()
            self.takeoff_created.emit(
                self._place_session_uid,
                pos,
                self._current_bid_page_uid or "",
            )
        else:
            self.update_place_preview(scene_pos)
        event.accept()
        return True

    def handle_place_release_linear(self, event) -> bool:
        condition = self._current_conditions.get(self._place_session_uid)
        if not (
            condition is not None
            and condition.layer_visible
            and condition.condition_type == Condition.TYPE_LINEAR
            and self._place_linear_dragging
            and self._place_points
        ):
            return False
        scene_pos = self.mapToScene(event.pos())
        ost_x2, ost_y2, _cx, _cy, snap_kind = self._placement_snap_from_scene(scene_pos)
        x1, y1 = self._place_points[0]
        ost_x2, ost_y2 = self._snap_angle_for_placement(
            x1, y1, ost_x2, ost_y2, snap_kind
        )
        min_len = self._snap_increments if self._snap_increments > 0 else 1e-6
        dist_ost = self._linear_geom.calc_chord_length(x1, y1, ost_x2, ost_y2)
        self._place_linear_dragging = False
        self._place_points = []
        self.clear_place_preview()
        if dist_ost >= min_len:
            if condition.is_curved_segment:
                mx = (x1 + ost_x2) / 2.0
                my = (y1 + ost_y2) / 2.0
                self._invalidate_snap_index()
                self.takeoff_created.emit(
                    self._place_session_uid,
                    [x1, y1, ost_x2, ost_y2, mx, my],
                    self._current_bid_page_uid or "",
                )
            else:
                self._invalidate_snap_index()
                self.takeoff_created.emit(
                    self._place_session_uid,
                    [x1, y1, ost_x2, ost_y2],
                    self._current_bid_page_uid or "",
                )
        event.accept()
        return True

    def enter_place_mode(self) -> bool:
        if not self._selected_uids:
            return False
        uid = next(iter(self._selected_uids))
        takeoff = self._current_takeoffs.get(uid)
        if not takeoff:
            return False
        return self.enter_place_mode_for_condition(takeoff.condition_uid)

    def enter_place_mode_for_condition(self, condition_uid: str) -> bool:
        condition = self._current_conditions.get(condition_uid)
        if not condition:
            return False
        if not condition.layer_visible:
            return False
        if condition.condition_type not in (
            Condition.TYPE_COUNT,
            Condition.TYPE_LINEAR,
            Condition.TYPE_AREA,
            Condition.TYPE_ATTACHMENT,
        ):
            return False
        self.clear_place_preview()
        if (
            self._backout_mode_active or self._backout_parent_uid
        ) and condition_uid != self._backout_active_uid:
            self._clear_backout_state()
        self._place_session_uid = condition_uid
        self._reset_place_session_state()
        return True

    def _reset_place_session_state(self) -> None:
        self._place_points = []
        self._place_linear_dragging = False
        self._place_area_rect_dragging = False
        self._backout_last_valid_ost = None
        self._set_area_placement_in_progress(False)

    def _finish_area_placement_preview_state(self) -> None:
        self.clear_place_preview()
        self._place_points = []
        self._set_area_placement_in_progress(False)
        self._invalidate_snap_index()

    def _apply_pattern_preview(
        self,
        item: QGraphicsPathItem,
        path: QPainterPath,
        condition,
        qcolor: QColor,
        opacity: float,
        page_transform,
        pattern_angle: float | None = None,
    ) -> None:
        fill_brush = None
        pattern_items = []
        if condition.is_linear or condition.display_grid_while_drawing:
            pattern_type = condition.pattern if condition.pattern else 1
            spacing = condition.spacing if condition.spacing else 4.0
            fill_brush, pattern_items = self._scene_builder.build_pattern_fill(
                path,
                pattern_type,
                qcolor,
                opacity,
                spacing,
                2.0,
                pattern_angle if condition.is_linear else None,
            )
        border_pen = QPen(qcolor)
        border_pen.setWidthF(2.0)
        border_pen.setCosmetic(True)
        item.setPen(border_pen)
        if fill_brush is not None:
            item.setBrush(fill_brush)
        else:
            item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        item.setZValue(10)
        self._add_preview_item(item, page_transform)
        for pitem in pattern_items:
            pitem.setZValue(10)
            self._add_preview_item(pitem, page_transform)

    def _add_secondary_condition_previews(
        self,
        path: QPainterPath,
        page_transform,
        base_opacity: float,
        linear_endpoints=None,
    ) -> None:
        if not self._place_all_condition_uids:
            return
        cs = self._scene_builder.get_coordinate_system() if linear_endpoints else None
        for cond_uid in self._place_all_condition_uids:
            cond = self._current_conditions.get(cond_uid)
            if not cond:
                continue
            color_hex, opacity = self._condition_preview_color_and_opacity(
                cond_uid, cond, default_opacity=base_opacity
            )
            qcolor = QColor(color_hex)
            if linear_endpoints and cs:
                x1, y1, x2, y2 = linear_endpoints
                cond_path = self._build_linear_path(cs, cond, x1, y1, x2, y2)
                pattern_angle = compute_line_angle(x1, y1, x2, y2)
            else:
                cond_path = path
                pattern_angle = None
            item = QGraphicsPathItem()
            item.setPath(cond_path)
            self._apply_pattern_preview(
                item,
                cond_path,
                cond,
                qcolor,
                opacity,
                page_transform,
                pattern_angle,
            )

    def _build_linear_path(self, cs, condition, x1, y1, x2, y2) -> QPainterPath:
        thickness_ost = condition.thickness if condition.thickness else 1.0
        view_scale = cs.page_info.get("view_scale", 1.0)
        thickness_px = cs.ost_to_pdf_points(thickness_ost) * view_scale
        thickness_px = max(thickness_px, 2.0)
        dx, dy = x2 - x1, y2 - y1
        length = math.sqrt(dx * dx + dy * dy)
        if length < 0.001:
            return QPainterPath()
        dx_n, dy_n = dx / length, dy / length
        px, py = -dy_n * thickness_px / 2, dx_n * thickness_px / 2
        path = QPainterPath()
        path.moveTo(x1 + px, y1 + py)
        path.lineTo(x1 - px, y1 - py)
        path.lineTo(x2 - px, y2 - py)
        path.lineTo(x2 + px, y2 + py)
        path.closeSubpath()
        return path

    def _exit_place_mode(self) -> None:
        was_active = self._place_session_uid is not None
        self.clear_place_preview()
        self._reset_place_session_state()
        self._place_all_condition_uids = []
        self._place_session_uid = None
        if was_active:
            self._apply_cursor_mode("select")
            self.place_exited.emit()

    @staticmethod
    def _path_from_transformed_polygon(points: list) -> QPainterPath:
        path = QPainterPath()
        path.moveTo(points[0], points[1])
        for i in range(2, len(points) - 1, 2):
            path.lineTo(points[i], points[i + 1])
        path.closeSubpath()
        return path

    def _find_area_at(self, ost_x: float, ost_y: float) -> str:
        cs = self._scene_builder.get_coordinate_system()
        pt_tx = cs.transform_vertices_to_2d([ost_x, ost_y])
        pt = QtCore.QPointF(pt_tx[0], pt_tx[1])
        for t in self._current_takeoffs.values():
            if t.is_hole:
                continue
            cond = self._current_conditions.get(t.condition_uid)
            if not cond or not cond.is_area:
                continue
            t_pos = cs.parse_position(t.position)
            if not t_pos or len(t_pos) < 6:
                continue
            t_tx = cs.transform_vertices_to_2d(t_pos)
            path = self._path_from_transformed_polygon(t_tx)
            if path.contains(pt):
                return t.uid
        return ""

    def _point_in_sibling_hole(self, ost_x: float, ost_y: float) -> bool:
        if not self._backout_parent_uid:
            return False
        cs = self._scene_builder.get_coordinate_system()
        pt_tx = cs.transform_vertices_to_2d([ost_x, ost_y])
        pt = QtCore.QPointF(pt_tx[0], pt_tx[1])
        for sibling in self._current_takeoffs.values():
            if sibling.parent_uid != self._backout_parent_uid:
                continue
            sib_pos = cs.parse_position(sibling.position)
            if not sib_pos or len(sib_pos) < 6:
                continue
            sib_tx = cs.transform_vertices_to_2d(sib_pos)
            sib_path = self._path_from_transformed_polygon(sib_tx)
            if sib_path.contains(pt):
                return True
        return False

    def _check_hole_overlap(
        self, pos_flat: list, parent_uid: str = None, exclude_uid: str = None
    ) -> bool:
        parent_uid = parent_uid or self._backout_parent_uid
        if not parent_uid:
            return False
        cs = self._scene_builder.get_coordinate_system()
        new_tx = cs.transform_vertices_to_2d(pos_flat)
        new_path = self._path_from_transformed_polygon(new_tx)
        parent = self._current_takeoffs.get(parent_uid)
        if parent:
            parent_pos = cs.parse_position(parent.position)
            if parent_pos and len(parent_pos) >= 6:
                parent_tx = cs.transform_vertices_to_2d(parent_pos)
                parent_path = self._path_from_transformed_polygon(parent_tx)
                if not new_path.subtracted(parent_path).isEmpty():
                    return True
        for sibling in self._current_takeoffs.values():
            if sibling.parent_uid != parent_uid:
                continue
            if exclude_uid and sibling.uid == exclude_uid:
                continue
            sib_pos = cs.parse_position(sibling.position)
            if not sib_pos or len(sib_pos) < 6:
                continue
            sib_tx = cs.transform_vertices_to_2d(sib_pos)
            sib_path = self._path_from_transformed_polygon(sib_tx)
            if new_path.intersects(sib_path):
                return True
        return False

    def _update_parent_hole_preview(self, hole_path: QPainterPath) -> None:
        cs = self._scene_builder.get_coordinate_system()
        parent = self._current_takeoffs.get(self._backout_parent_uid)
        if not parent:
            return
        parent_pos = cs.parse_position(parent.position)
        if not parent_pos or len(parent_pos) < 6:
            return
        parent_tx = cs.transform_vertices_to_2d(parent_pos)
        combined = self._path_from_transformed_polygon(parent_tx)
        for child in self._current_takeoffs.values():
            if child.parent_uid != self._backout_parent_uid:
                continue
            child_pos = cs.parse_position(child.position)
            if not child_pos or len(child_pos) < 6:
                continue
            child_tx = cs.transform_vertices_to_2d(child_pos)
            child_path = self._path_from_transformed_polygon(child_tx)
            combined = combined.subtracted(child_path)
        combined = combined.subtracted(hole_path)
        parent_items = self._uid_to_items.get(self._backout_parent_uid, [])
        for item in parent_items:
            if isinstance(item, QGraphicsPathItem):
                if not self._backout_orig_parent_path:
                    self._backout_orig_parent_path = item.path()
                item.setPath(combined)
                break

    def _set_area_placement_in_progress(self, in_progress: bool) -> None:
        if self._area_in_progress == in_progress:
            return
        self._area_in_progress = in_progress
        self.area_placement_in_progress.emit(in_progress)

    def _paste_backout_compute_translations(self, cursor_scene: QtCore.QPointF) -> list:
        sources = self._paste_backout_sources
        if not sources:
            return []
        gx, gy = self._paste_backout_group_centroid
        cursor_ost = self._scene_pos_to_ost(cursor_scene)
        dx = self.snap_ost(cursor_ost.x()) - gx
        dy = self.snap_ost(cursor_ost.y()) - gy
        translated: list = []
        for src in sources:
            pos = src["position"]
            n = len(pos) // 2
            new_pos = []
            for i in range(n):
                new_pos.append(pos[i * 2] + dx)
                new_pos.append(pos[i * 2 + 1] + dy)
            translated.append(new_pos)
        return translated

    def _paste_backout_validate_all(self, translated_list: list) -> tuple:
        results = []
        for pos in translated_list:
            n = len(pos) // 2
            cx = sum(pos[i * 2] for i in range(n)) / n
            cy = sum(pos[i * 2 + 1] for i in range(n)) / n
            parent_uid = self._find_area_at(cx, cy)
            if not parent_uid:
                results.append(("", False))
                continue
            if self._check_hole_overlap(pos, parent_uid=parent_uid):
                results.append((parent_uid, False))
                continue
            results.append((parent_uid, True))
        all_valid = bool(results) and all(r[1] for r in results)
        return results, all_valid

    def clear_paste_backout_preview(self) -> None:
        for item in self._paste_backout_preview_items:
            try:
                self._scene.removeItem(item)
            except (TypeError, RuntimeError):
                pass
        self._paste_backout_preview_items.clear()

    def update_paste_backout_preview(self, cursor_scene: QtCore.QPointF) -> None:
        self.clear_paste_backout_preview()
        if not self._paste_backout_active:
            return
        translated_list = self._paste_backout_compute_translations(cursor_scene)
        if not translated_list:
            return
        results, _ = self._paste_backout_validate_all(translated_list)
        cs = self._scene_builder.get_coordinate_system()
        page_transform = self._current_page_transform()
        for pos, (_, is_valid) in zip(translated_list, results):
            tx = cs.transform_vertices_to_2d(pos)
            if len(tx) < 4:
                continue
            path = self._path_from_transformed_polygon(tx)
            color = QColor(30, 160, 70) if is_valid else QColor(200, 0, 0)
            self._add_dashed_path_preview(
                path,
                color,
                15,
                page_transform,
                target_list=self._paste_backout_preview_items,
                pen_width=2.0,
            )

    def refresh_paste_backout_preview_after_view_change(self) -> None:
        if self._last_mouse_vp_pos is not None:
            self.update_paste_backout_preview(self.mapToScene(self._last_mouse_vp_pos))
        self.viewport().update()

    def handle_paste_backout_press(self, event) -> bool:
        if not self._paste_backout_active:
            return False
        scene_pos = self.mapToScene(event.pos())
        translated_list = self._paste_backout_compute_translations(scene_pos)
        results, all_valid = self._paste_backout_validate_all(translated_list)
        if not all_valid:
            event.accept()
            return True
        page_uid = self._current_bid_page_uid or ""
        placements = []
        for src, pos, (parent_uid, _) in zip(
            self._paste_backout_sources, translated_list, results
        ):
            placements.append(
                {
                    "condition_uid": src["condition_uid"],
                    "position": pos,
                    "page_uid": page_uid,
                    "parent_uid": parent_uid,
                    "rotation": src["rotation"],
                    "is_negative": src["is_negative"],
                    "extras": dict(src["extras"]),
                }
            )
        source_bid_uid = self._paste_backout_source_bid_uid
        self.paste_backouts_placed.emit(placements, source_bid_uid)
        self.cancel_paste_backout()
        event.accept()
        return True
