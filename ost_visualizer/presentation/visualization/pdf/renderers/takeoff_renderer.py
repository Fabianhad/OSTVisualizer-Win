from typing import Any, List, Optional, Tuple
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsTextItem
from .....application.interfaces.i_coordinate_transformer import ICoordinateTransformer
from .....domain.entities import pattern as pt
from .....domain.entities import shape as shapes
from .....domain.entities.annotation import int_color_to_hex
from .....domain.entities.condition import Condition
from .....domain.entities.takeoff import Takeoff
from .....domain.services.uom_service import (
    calculate_condition_quantities,
    get_uom_label,
)
from ...core.geometry.ost_linear_geom import (
    gen_curve_pts,
    gen_thick_curve_offsets,
    proc_curved_pos,
)
from ...core.geometry.takeoff_geometry import (
    compute_count_vertices,
    compute_curved_linear_vertices,
    compute_line_angle,
    compute_straight_linear_vertices,
)
from ...pdf.renderers import pattern_renderer as pr
from ...services.color_service import ColorService


class TakeoffRenderer:
    def __init__(
        self, coord_system: ICoordinateTransformer, color_service: ColorService
    ):
        self._cs = coord_system
        self._color_service = color_service

    @property
    def coordinate_system(self) -> ICoordinateTransformer:
        return self._cs

    def set_page_info(self, page_info: dict[str, Any]) -> None:
        self._cs.update_page_info(page_info)

    def _build_item(
        self,
        path: QPainterPath,
        condition,
        color: str,
        opacity: float,
        line_width: float,
        uid: str,
        condition_uid: str,
        is_negative: bool = False,
        takeoff: Takeoff | None = None,
        hole_positions: list[list[float]] | None = None,
    ) -> QGraphicsItem | list[QGraphicsItem]:
        pattern_type = condition.pattern if condition.pattern else 1
        qcolor = QColor(color)
        pen = QPen(qcolor)
        pen.setWidthF(line_width)
        pen.setCosmetic(True)
        fill_brush = pr.get_pattern_fill_brush(pattern_type, qcolor, opacity)
        item = QGraphicsPathItem(path)
        item.setPen(pen)
        if fill_brush is not None:
            item.setBrush(fill_brush)
        item.setData(0, uid)
        item.setData(1, condition_uid)
        items: list[QGraphicsItem] = [item]
        if condition.is_area and condition.grid:
            spacing_x, spacing_y = self._grid_spacing(condition)
            pattern_items = pr.create_grid_items(
                path, qcolor, spacing_x, spacing_y, line_width, self._cs
            )
            if pattern_items:
                for pitem in pattern_items:
                    pitem.setData(0, uid)
                    pitem.setData(1, condition_uid)
                items.extend(pattern_items)
        elif pattern_type in pt.LINE_PATTERNS:
            spacing = condition.spacing if condition.spacing else 4.0
            orientation_angle = (
                self._linear_pattern_angle(takeoff)
                if condition.is_linear and takeoff is not None
                else None
            )
            pattern_items = pr.create_pattern_items(
                path,
                pattern_type,
                qcolor,
                spacing,
                line_width,
                self._cs,
                orientation_angle,
            )
            if pattern_items:
                for pitem in pattern_items:
                    pitem.setData(0, uid)
                    pitem.setData(1, condition_uid)
                items.extend(pattern_items)
        if is_negative:
            neg_indicator = self._create_negative_indicator(path)
            if neg_indicator:
                if isinstance(neg_indicator, list):
                    for ind_item in neg_indicator:
                        ind_item.setData(0, uid)
                        ind_item.setData(1, condition_uid)
                    items.extend(neg_indicator)
                else:
                    neg_indicator.setData(0, uid)
                    neg_indicator.setData(1, condition_uid)
                    items.append(neg_indicator)
        label_items = self._create_condition_label_items(
            path, condition, qcolor, uid, takeoff, hole_positions
        )
        items.extend(label_items)
        return items if len(items) > 1 else items[0]

    def _linear_pattern_angle(self, takeoff: Takeoff) -> float | None:
        position = self._cs.parse_position(takeoff.position)
        if not position or len(position) < 4:
            return None
        tx = self._cs.transform_vertices_to_2d(position[:4])
        if len(tx) < 4:
            return None
        return compute_line_angle(tx[0], tx[1], tx[2], tx[3])

    def _grid_spacing(self, condition) -> tuple[float, float]:
        spacing_x = condition.grid_size1 if condition.grid_size1 > 0 else 0.0
        spacing_y = condition.grid_size2 if condition.grid_size2 > 0 else 0.0
        if condition.gap > 0:
            spacing_x += condition.gap if spacing_x > 0 else 0.0
            spacing_y += condition.gap if spacing_y > 0 else 0.0
        fallback = condition.spacing if condition.spacing > 0 else 4.0
        return spacing_x or fallback, spacing_y or fallback

    def _create_condition_label_items(
        self,
        path: QPainterPath,
        condition,
        color: QColor,
        uid: str,
        takeoff: Takeoff | None,
        hole_positions: list[list[float]] | None,
    ) -> list[QGraphicsTextItem]:
        labels: list[QGraphicsTextItem] = []
        dimension_label: QGraphicsTextItem | None = None
        if condition.is_area and condition.display_dimension:
            text = self._dimension_label_text(condition, takeoff, hole_positions)
            if text:
                dimension_label = self._create_centered_condition_text_item(
                    path,
                    text,
                    color,
                    uid,
                    condition.uid,
                    "display_dimension",
                    takeoff,
                )
                labels.append(dimension_label)
        if condition.display_name and condition.name:
            if condition.is_area:
                if dimension_label is not None:
                    labels.append(
                        self._create_condition_text_item_below_item(
                            dimension_label,
                            condition.name,
                            color,
                            uid,
                            condition.uid,
                            "display_name",
                            takeoff,
                            y_offset=4.0,
                        )
                    )
                else:
                    labels.append(
                        self._create_centered_condition_text_item(
                            path,
                            condition.name,
                            color,
                            uid,
                            condition.uid,
                            "display_name",
                            takeoff,
                        )
                    )
            else:
                labels.append(
                    self._create_condition_text_item(
                        path,
                        condition.name,
                        color,
                        uid,
                        condition.uid,
                        "display_name",
                        takeoff,
                        y_offset=4.0,
                    )
                )
        return labels

    def _make_condition_text_item(
        self,
        text: str,
        color: QColor,
        uid: str,
        condition_uid: str,
        label_kind: str,
        takeoff: Takeoff | None,
    ) -> QGraphicsTextItem:
        item = QGraphicsTextItem(text)
        style = self._takeoff_label_style(takeoff, label_kind)
        has_label_style = any(value is not None for value in style[:3]) or any(
            bool(value) for value in style[3:]
        )
        label_color = (
            QColor(int_color_to_hex(style[1]))
            if has_label_style and style[1] is not None
            else color
        )
        item.setDefaultTextColor(label_color)
        font = QFont()
        font.setFamily(style[0] or font.family())
        font.setPointSize(style[2] or 9)
        font.setBold(bool(style[3]))
        font.setItalic(bool(style[4]))
        font.setUnderline(bool(style[5]))
        item.setFont(font)
        item.setData(0, uid)
        item.setData(1, condition_uid)
        item.setData(2, "condition_label")
        item.setData(3, label_kind)
        item.setZValue(20)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        return item

    def _takeoff_label_style(
        self, takeoff: Takeoff | None, label_kind: str
    ) -> tuple[Optional[str], Optional[int], Optional[int], bool, bool, bool]:
        if takeoff is None:
            return None, None, None, False, False, False
        if label_kind == "display_dimension":
            return (
                takeoff.dimension_font_name,
                takeoff.dimension_font_color,
                takeoff.dimension_font_size,
                takeoff.dimension_font_bold,
                takeoff.dimension_font_italic,
                takeoff.dimension_font_underline,
            )
        return (
            takeoff.name_font_name,
            takeoff.name_font_color,
            takeoff.name_font_size,
            takeoff.name_font_bold,
            takeoff.name_font_italic,
            takeoff.name_font_underline,
        )

    def _create_condition_text_item(
        self,
        path: QPainterPath,
        text: str,
        color: QColor,
        uid: str,
        condition_uid: str,
        label_kind: str,
        takeoff: Takeoff | None,
        y_offset: float,
    ) -> QGraphicsTextItem:
        item = self._make_condition_text_item(
            text, color, uid, condition_uid, label_kind, takeoff
        )
        bounds = path.boundingRect()
        text_bounds = item.boundingRect()
        item.setPos(
            bounds.center().x() - text_bounds.width() / 2.0,
            bounds.bottom() + y_offset,
        )
        return item

    def _create_centered_condition_text_item(
        self,
        path: QPainterPath,
        text: str,
        color: QColor,
        uid: str,
        condition_uid: str,
        label_kind: str,
        takeoff: Takeoff | None,
    ) -> QGraphicsTextItem:
        item = self._make_condition_text_item(
            text, color, uid, condition_uid, label_kind, takeoff
        )
        center = self._path_centroid(path)
        if center is None:
            bounds_center = path.boundingRect().center()
            center = bounds_center.x(), bounds_center.y()
        text_bounds = item.boundingRect()
        item.setPos(
            center[0] - text_bounds.width() / 2.0,
            center[1] - text_bounds.height() / 2.0,
        )
        return item

    def _create_condition_text_item_below_item(
        self,
        anchor_item: QGraphicsTextItem,
        text: str,
        color: QColor,
        uid: str,
        condition_uid: str,
        label_kind: str,
        takeoff: Takeoff | None,
        y_offset: float,
    ) -> QGraphicsTextItem:
        item = self._make_condition_text_item(
            text, color, uid, condition_uid, label_kind, takeoff
        )
        anchor_bounds = anchor_item.boundingRect()
        anchor_center_x = anchor_item.pos().x() + anchor_bounds.width() / 2.0
        text_bounds = item.boundingRect()
        item.setPos(
            anchor_center_x - text_bounds.width() / 2.0,
            anchor_item.pos().y() + anchor_bounds.height() + y_offset,
        )
        return item

    def _dimension_label_text(
        self,
        condition,
        takeoff: Takeoff | None,
        hole_positions: list[list[float]] | None,
    ) -> str:
        if takeoff is None:
            return ""
        q1, q2, q3 = calculate_condition_quantities(
            condition_type=condition.condition_type,
            calc_type1=condition.calc_type1,
            calc_type2=condition.calc_type2,
            calc_type3=condition.calc_type3,
            uom1=condition.uom1,
            uom2=condition.uom2,
            uom3=condition.uom3,
            width=condition.width,
            height=condition.height,
            depth=condition.depth,
            thickness=condition.thickness,
            position=takeoff.position,
            hole_positions=hole_positions,
            rise=condition.rise,
            run=condition.run,
            grid_size1=condition.grid_size1,
            grid_size2=condition.grid_size2,
            gap=condition.gap,
            round_quantity=condition.round_quantity,
            round_up=condition.round_up,
        )
        values = ((q1, condition.uom1), (q2, condition.uom2), (q3, condition.uom3))
        return "\n".join(f"{value:.2f} {get_uom_label(uom)}" for value, uom in values)

    def build_pattern_fill(
        self,
        path: QPainterPath,
        pattern_type: int,
        color: QColor,
        opacity: float,
        spacing: float,
        line_width: float,
        orientation_angle: float | None = None,
    ) -> Tuple[Optional[QBrush], List[QGraphicsPathItem]]:
        fill_brush = pr.get_pattern_fill_brush(pattern_type, color, opacity)
        pattern_items: List[QGraphicsPathItem] = []
        if pattern_type in pt.LINE_PATTERNS:
            pattern_items = pr.create_pattern_items(
                path,
                pattern_type,
                color,
                spacing,
                line_width,
                self._cs,
                orientation_angle,
            )
        return fill_brush, pattern_items

    def _create_negative_indicator(
        self, path: QPainterPath
    ) -> QGraphicsPathItem | list[QGraphicsPathItem] | None:
        center = self._path_centroid(path)
        if center is None:
            return None
        cx, cy = center
        rect_w, rect_h = 12.0, 12.0
        minus_w, minus_h = 6.0, 1.5
        rect_path = QPainterPath()
        rect_path.addRect(-rect_w / 2, -rect_h / 2, rect_w, rect_h)
        rect_item = QGraphicsPathItem(rect_path)
        border_pen = QPen(Qt.GlobalColor.black)
        border_pen.setWidthF(1.0)
        rect_item.setPen(border_pen)
        rect_item.setBrush(QBrush(Qt.GlobalColor.red))
        rect_item.setZValue(10)
        rect_item.setPos(cx, cy)
        rect_item.setFlag(QGraphicsPathItem.GraphicsItemFlag.ItemIgnoresTransformations)
        minus_path = QPainterPath()
        minus_path.addRect(-minus_w / 2, -minus_h / 2, minus_w, minus_h)
        minus_item = QGraphicsPathItem(minus_path)
        minus_item.setPen(QPen(Qt.GlobalColor.white))
        minus_item.setBrush(QBrush(Qt.GlobalColor.white))
        minus_item.setZValue(11)
        minus_item.setPos(cx, cy)
        minus_item.setFlag(
            QGraphicsPathItem.GraphicsItemFlag.ItemIgnoresTransformations
        )
        return [rect_item, minus_item]

    def _path_centroid(self, path: QPainterPath) -> tuple[float, float] | None:
        points = []
        for i in range(path.elementCount()):
            elem = path.elementAt(i)
            if elem.type.value in (0, 1):
                points.append((elem.x, elem.y))
        if len(points) < 3:
            return None
        centroid = self._calculate_polygon_centroid(points)
        if path.contains(QPointF(*centroid)):
            return centroid
        return self._nearest_interior_anchor(path, centroid, points)

    @staticmethod
    def _nearest_interior_anchor(
        path: QPainterPath,
        preferred: tuple[float, float],
        vertices: list[tuple[float, float]],
    ) -> tuple[float, float]:
        candidates: list[tuple[float, float]] = []
        for vx, vy in vertices:
            for fraction in (0.01, 0.05, 0.1, 0.25, 0.5):
                candidate = (
                    vx + (preferred[0] - vx) * fraction,
                    vy + (preferred[1] - vy) * fraction,
                )
                if path.contains(QPointF(*candidate)):
                    candidates.append(candidate)
        bounds = path.boundingRect()
        divisions = 32
        if bounds.width() > 0 and bounds.height() > 0:
            for row in range(divisions):
                y = bounds.top() + bounds.height() * (row + 0.5) / divisions
                for column in range(divisions):
                    x = bounds.left() + bounds.width() * (column + 0.5) / divisions
                    if path.contains(QPointF(x, y)):
                        candidates.append((x, y))
        if not candidates:
            return preferred
        return min(
            candidates,
            key=lambda point: (point[0] - preferred[0]) ** 2
            + (point[1] - preferred[1]) ** 2,
        )

    def _calculate_polygon_centroid(
        self, points: list[tuple[float, float]]
    ) -> tuple[float, float]:
        n = len(points)
        area = 0.0
        cx = 0.0
        cy = 0.0
        for i in range(n):
            x0, y0 = points[i]
            x1, y1 = points[(i + 1) % n]
            cross = x0 * y1 - x1 * y0
            area += cross
            cx += (x0 + x1) * cross
            cy += (y0 + y1) * cross
        area *= 0.5
        if abs(area) < 1e-10:
            return sum(p[0] for p in points) / n, sum(p[1] for p in points) / n
        factor = 1.0 / (6.0 * area)
        return cx * factor, cy * factor

    def _create_path_item(
        self,
        takeoff: dict,
        condition,
        color: str,
        opacity: float = 0.5,
        line_width: float = 2.0,
    ) -> QGraphicsPathItem | list[QGraphicsPathItem] | None:
        position = self._cs.parse_position(takeoff.position)
        if not position or len(position) < 2:
            return None
        path = self._create_path(condition, position, takeoff)
        if path is None or path.isEmpty():
            return None
        is_negative = takeoff.is_negative
        return self._build_item(
            path,
            condition,
            color,
            opacity,
            line_width,
            takeoff.uid,
            takeoff.condition_uid,
            is_negative,
            takeoff=takeoff,
            hole_positions=None,
        )

    def _create_path(
        self,
        condition,
        position: list[float],
        takeoff: dict,
    ) -> QPainterPath | None:
        if condition.is_area and (len(position) < 6 or len(position) % 2):
            return None
        tx_position = self._cs.transform_vertices_to_2d(position)
        if condition.is_linear:
            return self._create_linear_path(position, tx_position, takeoff, condition)
        elif condition.is_area:
            return self._create_area_path(tx_position, takeoff)
        elif condition.is_count or condition.is_attachment:
            return self._create_count_path(tx_position, takeoff, condition)
        return None

    @staticmethod
    def _vertices_to_path(
        vertices: list[tuple[float, float]],
    ) -> QPainterPath:
        path = QPainterPath()
        path.moveTo(vertices[0][0], vertices[0][1])
        for x, y in vertices[1:]:
            path.lineTo(x, y)
        path.closeSubpath()
        return path

    def _create_linear_path(
        self,
        raw_position: list[float],
        position: list[float],
        takeoff: dict,
        condition,
    ) -> QPainterPath | None:
        if len(position) < 4:
            return None
        curve = takeoff.curve
        thickness_ost = condition.thickness if condition.thickness else 1.0
        view_scale = self._cs.page_info.get("view_scale", 1.0)
        thickness_px = self._cs.ost_to_pdf_points(thickness_ost) * view_scale
        thickness_px = max(thickness_px, 2.0)
        if curve >= 0 and len(raw_position) >= 6:
            rx1, ry1, rx2, ry2, rcx, rcy = raw_position[:6]
            rx1, ry1, rx2, ry2, rcx, rcy = proc_curved_pos(
                raw_position, rx1, ry1, rx2, ry2, rcx, rcy
            )
            tx = self._cs.transform_vertices_to_2d([rx1, ry1, rx2, ry2, rcx, rcy])
            verts = compute_curved_linear_vertices(
                tx[0],
                tx[1],
                tx[2],
                tx[3],
                tx[4],
                tx[5],
                gen_curve_pts,
                gen_thick_curve_offsets,
                thickness_px,
            )
            if not verts:
                return None
            return self._vertices_to_path(verts)
        x1, y1, x2, y2 = position[0], position[1], position[2], position[3]
        verts = compute_straight_linear_vertices(x1, y1, x2, y2, thickness_px)
        if not verts:
            return None
        return self._vertices_to_path(verts)

    def _create_area_path(
        self, position: list[float], takeoff: dict | None = None
    ) -> QPainterPath | None:
        if len(position) < 6 or len(position) % 2:
            return None
        points = [(position[i], position[i + 1]) for i in range(0, len(position), 2)]
        if len(points) < 3:
            return None
        path = QPainterPath()
        path.moveTo(points[0][0], points[0][1])
        for x, y in points[1:]:
            path.lineTo(x, y)
        path.closeSubpath()
        return path

    def _create_count_path(
        self,
        position: list[float],
        takeoff: dict,
        condition,
    ) -> QPainterPath | None:
        if len(position) < 2:
            return None
        x, y = position[0], position[1]
        shape_id = condition.shape if condition.shape else shapes.SQUARE
        width_ost = max(condition.width if condition.width else 1, 1)
        if shape_id == shapes.SQUARE or shape_id == shapes.CIRCLE:
            depth_ost = width_ost
        else:
            depth_ost = max(condition.depth if condition.depth else width_ost, 1)
        if condition.is_count:
            scale = max(condition.display_size, 0.1) / 100.0
            width_ost *= scale
            depth_ost *= scale
        view_scale = self._cs.page_info.get("view_scale", 1.0)
        width_px = self._cs.ost_to_pdf_points(width_ost) * view_scale
        depth_px = self._cs.ost_to_pdf_points(depth_ost) * view_scale
        min_dim = min(width_px, depth_px)
        if 0 < min_dim < 8.0:
            scale = 8.0 / min_dim
            width_px *= scale
            depth_px *= scale
        rotation = takeoff.rotation
        verts = compute_count_vertices(x, y, shape_id, width_px, depth_px, rotation)
        return self._vertices_to_path(verts)

    def create_all_path_items(
        self,
        takeoffs: list[Takeoff],
        conditions: dict[str, Condition],
        color_map: dict[str, str],
        opacity: float = 0.5,
        page_info: dict[str, Any] | None = None,
        page_area_selections: dict[str, str | None] | None = None,
    ) -> list[tuple[str, QGraphicsPathItem | list[QGraphicsPathItem]]]:
        if page_info:
            self.set_page_info(page_info)
        takeoff_map = {t.uid: t for t in takeoffs}
        area_holes_map: dict[str, list[Takeoff]] = {}
        child_uids: set = set()
        for takeoff in takeoffs:
            parent_uid = takeoff.parent_uid
            if parent_uid and str(parent_uid) != "0" and parent_uid != 0:
                if parent_uid in takeoff_map:
                    parent = takeoff_map[parent_uid]
                    parent_condition_uid = parent.condition_uid
                    if parent_condition_uid in conditions:
                        parent_condition = conditions[parent_condition_uid]
                        child_condition = conditions.get(takeoff.condition_uid)
                        if (
                            parent_condition.is_area
                            and child_condition
                            and child_condition.is_area
                        ):
                            area_holes_map.setdefault(parent_uid, []).append(takeoff)
                            child_uids.add(takeoff.uid)
        items = []
        for takeoff in takeoffs:
            takeoff_uid = takeoff.uid
            if takeoff_uid in child_uids:
                continue
            condition_uid = takeoff.condition_uid
            if condition_uid not in conditions:
                continue
            condition = conditions[condition_uid]
            if condition_uid not in color_map:
                continue
            color_entry = color_map[condition_uid]
            color = color_entry.hex
            item_opacity = color_entry.opacity
            if self._color_service.should_gray_out_takeoff(
                takeoff, page_area_selections
            ):
                color = "#808080"
            holes = area_holes_map.get(takeoff_uid, [])
            if holes and condition.condition_type == Condition.TYPE_AREA:
                result = self._create_area_with_holes(
                    takeoff, condition, holes, color, item_opacity
                )
            else:
                result = self._create_path_item(takeoff, condition, color, item_opacity)
            if result:
                items.append((takeoff_uid, result))
        for hole_uid in child_uids:
            hole_takeoff = takeoff_map.get(hole_uid)
            if not hole_takeoff:
                continue
            hole_condition = conditions.get(hole_takeoff.condition_uid)
            if not hole_condition:
                continue
            position = self._cs.parse_position(hole_takeoff.position)
            if not position or len(position) < 6 or len(position) % 2:
                continue
            tx = self._cs.transform_vertices_to_2d(position)
            hole_path = self._create_area_path(tx, hole_takeoff)
            if hole_path and not hole_path.isEmpty():
                hole_item = QGraphicsPathItem()
                hole_item.setPath(hole_path)
                hole_item.setPen(QPen(Qt.PenStyle.NoPen))
                hole_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                hole_item.setZValue(0)
                hole_item.setData(0, hole_uid)
                items.append((hole_uid, hole_item))
        return items

    def _create_area_with_holes(
        self,
        takeoff: dict,
        condition,
        holes: list[dict],
        color: str,
        opacity: float,
    ) -> QGraphicsPathItem | list[QGraphicsPathItem] | None:
        position = self._cs.parse_position(takeoff.position)
        if not position or len(position) < 6 or len(position) % 2:
            return None
        tx_position = self._cs.transform_vertices_to_2d(position)
        parent_path = self._create_area_path(tx_position, takeoff)
        if parent_path is None or parent_path.isEmpty():
            return None
        for hole_takeoff in holes:
            hole_position = self._cs.parse_position(hole_takeoff.position)
            if not hole_position or len(hole_position) < 6 or len(hole_position) % 2:
                continue
            tx_hole_position = self._cs.transform_vertices_to_2d(hole_position)
            hole_path = self._create_area_path(tx_hole_position, hole_takeoff)
            if hole_path and not hole_path.isEmpty():
                parent_path = parent_path.subtracted(hole_path)
        if parent_path.isEmpty():
            return None
        is_negative = takeoff.is_negative
        return self._build_item(
            parent_path,
            condition,
            color,
            opacity,
            2.0,
            takeoff.uid,
            takeoff.condition_uid,
            is_negative,
            takeoff=takeoff,
            hole_positions=[hole.position for hole in holes if hole.position],
        )
