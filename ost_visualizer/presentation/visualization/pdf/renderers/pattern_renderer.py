import math
from typing import List, Tuple
from PySide6.QtGui import QBrush, QColor, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsPathItem
from .....application.interfaces.i_coordinate_transformer import ICoordinateTransformer
from .....domain.entities import pattern as pt


def get_pattern_fill_brush(
    pattern_type: int, qcolor: QColor, base_opacity: float = 1.0
) -> QBrush | None:
    if pattern_type in pt.LINE_PATTERNS or pattern_type == pt.NONE:
        return None
    fill_color = QColor(qcolor)
    fill_color.setAlphaF(base_opacity)
    return QBrush(fill_color)


def create_pattern_items(
    base_path: QPainterPath,
    pattern_type: int,
    color: QColor,
    spacing: float,
    line_width: float,
    coord_system: ICoordinateTransformer | None = None,
) -> List[QGraphicsPathItem]:
    if pattern_type not in pt.LINE_PATTERNS:
        return []
    pattern_spacing = _convert_spacing(spacing, coord_system)
    diag_spacing = pattern_spacing * math.sqrt(2)
    bounds = base_path.boundingRect()
    min_x, min_y = bounds.left(), bounds.top()
    max_x, max_y = bounds.right(), bounds.bottom()
    polygon_points = _extract_polygon_points(base_path)
    if len(polygon_points) < 3:
        return []
    items: List[QGraphicsPathItem] = []
    pen = QPen(color)
    pen.setWidthF(line_width)
    pen.setCosmetic(True)
    if pattern_type == pt.HORIZONTAL:
        items.extend(
            _create_horizontal_lines(polygon_points, min_y, max_y, pattern_spacing, pen)
        )
    elif pattern_type == pt.VERTICAL:
        items.extend(
            _create_vertical_lines(polygon_points, min_x, max_x, pattern_spacing, pen)
        )
    elif pattern_type == pt.BACKWARD_DIAG:
        items.extend(
            _create_diagonal_lines(
                polygon_points,
                min_x,
                min_y,
                max_x,
                max_y,
                diag_spacing,
                pen,
                backward=True,
            )
        )
    elif pattern_type == pt.FORWARD_DIAG:
        items.extend(
            _create_diagonal_lines(
                polygon_points,
                min_x,
                min_y,
                max_x,
                max_y,
                diag_spacing,
                pen,
                backward=False,
            )
        )
    elif pattern_type == pt.CROSSHATCH:
        items.extend(
            _create_horizontal_lines(polygon_points, min_y, max_y, pattern_spacing, pen)
        )
        items.extend(
            _create_vertical_lines(polygon_points, min_x, max_x, pattern_spacing, pen)
        )
    elif pattern_type == pt.DIAG_CROSSHATCH:
        items.extend(
            _create_diagonal_lines(
                polygon_points,
                min_x,
                min_y,
                max_x,
                max_y,
                diag_spacing,
                pen,
                backward=True,
            )
        )
        items.extend(
            _create_diagonal_lines(
                polygon_points,
                min_x,
                min_y,
                max_x,
                max_y,
                diag_spacing,
                pen,
                backward=False,
            )
        )
    return items


def _convert_spacing(
    spacing: float, coord_system: ICoordinateTransformer | None
) -> float:
    if coord_system is not None and spacing > 0:
        pdf_spacing = coord_system.ost_to_pdf_points(spacing)
        view_scale = coord_system.page_info.get("view_scale", 1.0)
        return pdf_spacing * view_scale
    return spacing if spacing > 0 else 72.0


def _extract_polygon_points(path: QPainterPath) -> List[Tuple[float, float]]:
    points = []
    for i in range(path.elementCount()):
        elem = path.elementAt(i)
        if elem.type.value in (0, 1):
            points.append((elem.x, elem.y))
    return points


def _create_horizontal_lines(
    polygon: List[Tuple[float, float]],
    min_y: float,
    max_y: float,
    spacing: float,
    pen: QPen,
) -> List[QGraphicsPathItem]:
    items = []
    y = min_y + spacing
    while y < max_y:
        intersections = _find_horizontal_line_intersections(y, polygon)
        for i in range(0, len(intersections) - 1, 2):
            line_path = QPainterPath()
            line_path.moveTo(intersections[i], y)
            line_path.lineTo(intersections[i + 1], y)
            item = QGraphicsPathItem(line_path)
            item.setPen(pen)
            items.append(item)
        y += spacing
    return items


def _create_vertical_lines(
    polygon: List[Tuple[float, float]],
    min_x: float,
    max_x: float,
    spacing: float,
    pen: QPen,
) -> List[QGraphicsPathItem]:
    items = []
    x = min_x + spacing
    while x < max_x:
        intersections = _find_vertical_line_intersections(x, polygon)
        for i in range(0, len(intersections) - 1, 2):
            line_path = QPainterPath()
            line_path.moveTo(x, intersections[i])
            line_path.lineTo(x, intersections[i + 1])
            item = QGraphicsPathItem(line_path)
            item.setPen(pen)
            items.append(item)
        x += spacing
    return items


def _find_horizontal_line_intersections(
    y: float, polygon: List[Tuple[float, float]]
) -> List[float]:
    intersections = []
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 <= y < y2) or (y2 <= y < y1):
            if y2 != y1:
                x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                intersections.append(x)
    intersections.sort()
    return intersections


def _find_vertical_line_intersections(
    x: float, polygon: List[Tuple[float, float]]
) -> List[float]:
    intersections = []
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (x1 <= x < x2) or (x2 <= x < x1):
            if x2 != x1:
                y = y1 + (x - x1) * (y2 - y1) / (x2 - x1)
                intersections.append(y)
    intersections.sort()
    return intersections


def _create_diagonal_lines(
    polygon: List[Tuple[float, float]],
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    spacing: float,
    pen: QPen,
    backward: bool = True,
) -> List[QGraphicsPathItem]:
    items = []
    n = len(polygon)
    width = max_x - min_x
    height = max_y - min_y
    box_diag = math.sqrt(width**2 + height**2)
    if backward:
        c_min = min_x - max_y - box_diag
        c_max = max_x - min_y + box_diag
        c = c_min
        while c <= c_max:
            intersections = []
            for i in range(n):
                px, py = polygon[i]
                qx, qy = polygon[(i + 1) % n]
                dx, dy = qx - px, qy - py
                denom = dx - dy
                if abs(denom) > 1e-10:
                    t = (c - (px - py)) / denom
                    if 0 <= t <= 1:
                        ix = px + t * dx
                        iy = py + t * dy
                        intersections.append((ix, iy))
            intersections.sort(key=lambda p: p[0])
            for i in range(0, len(intersections) - 1, 2):
                x1, y1 = intersections[i]
                x2, y2 = intersections[i + 1]
                line_path = QPainterPath()
                line_path.moveTo(x1, y1)
                line_path.lineTo(x2, y2)
                item = QGraphicsPathItem(line_path)
                item.setPen(pen)
                items.append(item)
            c += spacing
    else:
        c_min = min_x + min_y - box_diag
        c_max = max_x + max_y + box_diag
        c = c_min
        while c <= c_max:
            intersections = []
            for i in range(n):
                px, py = polygon[i]
                qx, qy = polygon[(i + 1) % n]
                dx, dy = qx - px, qy - py
                denom = dx + dy
                if abs(denom) > 1e-10:
                    t = (c - (px + py)) / denom
                    if 0 <= t <= 1:
                        ix = px + t * dx
                        iy = py + t * dy
                        intersections.append((ix, iy))
            intersections.sort(key=lambda p: p[0])
            for i in range(0, len(intersections) - 1, 2):
                x1, y1 = intersections[i]
                x2, y2 = intersections[i + 1]
                line_path = QPainterPath()
                line_path.moveTo(x1, y1)
                line_path.lineTo(x2, y2)
                item = QGraphicsPathItem(line_path)
                item.setPen(pen)
                items.append(item)
            c += spacing
    return items
