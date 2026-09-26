import math
from collections.abc import Iterable
from dataclasses import dataclass
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainterPath, QPolygonF
from PySide6.QtWidgets import QGraphicsRectItem
from .....application.interfaces.i_linear_geometry import ILinearGeometry
from .....domain.entities.condition import Condition
from ....visualization.core.geometry.takeoff_geometry import (
    compute_count_vertices,
    resolve_point_takeoff_shape,
)
from . import ost_geom_utils as _native

segments_intersect = _native.segments_intersect
polygon_is_valid = _native.polygon_is_valid
polyline_self_intersects = _native.polyline_self_intersects
point_to_segment_distance = _native.point_to_segment_distance
signed_area = _native.signed_area


def _attachment_footprint_path(
    coordinate_system,
    condition: Condition,
    position: list[float],
    rotation: float,
) -> QPainterPath:
    if not condition.is_attachment or len(position) != 2:
        return QPainterPath()
    shape_id, width, depth = resolve_point_takeoff_shape(condition)
    vertices = compute_count_vertices(
        position[0],
        position[1],
        shape_id,
        width,
        depth,
        rotation,
    )
    flattened = [coordinate for vertex in vertices for coordinate in vertex]
    return position_polygon_path(coordinate_system, flattened)


def attachment_fits_area(
    coordinate_system,
    condition: Condition,
    position: list[float],
    rotation: float,
    parent_position: list[float],
    backout_positions: Iterable[list[float]],
) -> bool:
    footprint = _attachment_footprint_path(
        coordinate_system,
        condition,
        position,
        rotation,
    )
    parent = position_polygon_path(coordinate_system, parent_position)
    exclusions = (
        position_polygon_path(coordinate_system, backout_position)
        for backout_position in backout_positions
    )
    return path_fits_inside_excluding(footprint, parent, exclusions)


def closed_polygon_path(points: list[float]) -> QPainterPath:
    if len(points) < 6 or len(points) % 2:
        return QPainterPath()
    path = QPainterPath()
    path.addPolygon(
        QPolygonF(
            [
                QPointF(points[index], points[index + 1])
                for index in range(0, len(points), 2)
            ]
        )
    )
    path.closeSubpath()
    return path


def position_polygon_path(coordinate_system, position: list[float]) -> QPainterPath:
    if len(position) < 6 or len(position) % 2:
        return QPainterPath()
    transformed = coordinate_system.transform_vertices_to_2d(position)
    return closed_polygon_path(transformed)


def path_is_inside(candidate: QPainterPath, parent: QPainterPath) -> bool:
    return (
        not candidate.isEmpty()
        and not parent.isEmpty()
        and candidate.subtracted(parent).isEmpty()
    )


def path_intersects_any(
    candidate: QPainterPath, exclusions: Iterable[QPainterPath]
) -> bool:
    if candidate.isEmpty():
        return False
    return any(
        not exclusion.isEmpty() and candidate.intersects(exclusion)
        for exclusion in exclusions
    )


def path_fits_inside_excluding(
    candidate: QPainterPath,
    parent: QPainterPath,
    exclusions: Iterable[QPainterPath],
) -> bool:
    return path_is_inside(candidate, parent) and not path_intersects_any(
        candidate, exclusions
    )


@dataclass
class HandleInfo:
    item: QGraphicsRectItem
    cursor: Qt.CursorShape


def resize_cursor_for_edge(dx: float, dy: float) -> Qt.CursorShape:
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return Qt.CursorShape.SizeAllCursor
    perp_deg = math.degrees(math.atan2(dy, dx) + math.pi / 2) % 180
    if perp_deg < 22.5 or perp_deg >= 157.5:
        return Qt.CursorShape.SizeHorCursor
    elif perp_deg < 67.5:
        return Qt.CursorShape.SizeFDiagCursor
    elif perp_deg < 112.5:
        return Qt.CursorShape.SizeVerCursor
    else:
        return Qt.CursorShape.SizeBDiagCursor


def cursor_for_direction(dx: float, dy: float) -> Qt.CursorShape:
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return Qt.CursorShape.SizeAllCursor
    deg = math.degrees(math.atan2(dy, dx)) % 180
    if deg < 22.5 or deg >= 157.5:
        return Qt.CursorShape.SizeHorCursor
    elif deg < 67.5:
        return Qt.CursorShape.SizeFDiagCursor
    elif deg < 112.5:
        return Qt.CursorShape.SizeVerCursor
    else:
        return Qt.CursorShape.SizeBDiagCursor


def polygon_centroid(pos: list, n: int) -> tuple:
    area = 0.0
    cx_sum = 0.0
    cy_sum = 0.0
    origin_x, origin_y = pos[:2]
    for i in range(n):
        j = (i + 1) % n
        x_i, y_i = pos[i * 2] - origin_x, pos[i * 2 + 1] - origin_y
        x_j, y_j = pos[j * 2] - origin_x, pos[j * 2 + 1] - origin_y
        cross = x_i * y_j - x_j * y_i
        area += cross
        cx_sum += (x_i + x_j) * cross
        cy_sum += (y_i + y_j) * cross
    area *= 0.5
    if area != 0.0:
        return origin_x + cx_sum / (6.0 * area), origin_y + cy_sum / (6.0 * area)
    return (
        sum(pos[i * 2] for i in range(n)) / n,
        sum(pos[i * 2 + 1] for i in range(n)) / n,
    )


def rotate_position_coords(
    pos: list,
    deg: float,
    is_area: bool = False,
    is_curved: bool = False,
    is_linear: bool = False,
    linear_geom: ILinearGeometry = None,
) -> list:
    n = len(pos) // 2
    if n < 1:
        return list(pos)
    if is_curved and len(pos) >= 6 and linear_geom is not None:
        rx = list(pos[:6])
        rx[0], rx[1], rx[2], rx[3], rx[4], rx[5] = linear_geom.proc_curved_pos(
            pos, rx[0], rx[1], rx[2], rx[3], rx[4], rx[5]
        )
        cx, cy = rx[4], rx[5]
        rad = math.radians(deg)
        cos_r, sin_r = math.cos(rad), math.sin(rad)
        result = list(pos)
        for i in range(2):
            dx, dy = pos[i * 2] - cx, pos[i * 2 + 1] - cy
            result[i * 2] = cx + dx * cos_r - dy * sin_r
            result[i * 2 + 1] = cy + dx * sin_r + dy * cos_r
        return result
    if is_linear and n >= 2:
        rotate_n = 2
        cx = (pos[0] + pos[2]) / 2
        cy = (pos[1] + pos[3]) / 2
    elif is_area and n >= 3:
        rotate_n = n
        cx, cy = polygon_centroid(pos, n)
    else:
        rotate_n = n
        xs = [pos[i * 2] for i in range(n)]
        ys = [pos[i * 2 + 1] for i in range(n)]
        cx = (min(xs) + max(xs)) / 2
        cy = (min(ys) + max(ys)) / 2
    rad = math.radians(deg)
    cos_r, sin_r = math.cos(rad), math.sin(rad)
    result = list(pos)
    for i in range(rotate_n):
        dx, dy = pos[i * 2] - cx, pos[i * 2 + 1] - cy
        result[i * 2] = cx + dx * cos_r - dy * sin_r
        result[i * 2 + 1] = cy + dx * sin_r + dy * cos_r
    return result


def rotate_points_around(
    pos: list, deg: float, center_x: float, center_y: float
) -> list:
    n = len(pos) // 2
    if n < 1:
        return list(pos)
    rad = math.radians(deg)
    cos_r, sin_r = math.cos(rad), math.sin(rad)
    result = list(pos)
    for i in range(n):
        dx = pos[i * 2] - center_x
        dy = pos[i * 2 + 1] - center_y
        result[i * 2] = center_x + dx * cos_r - dy * sin_r
        result[i * 2 + 1] = center_y + dx * sin_r + dy * cos_r
    return result


def mirror_points_around(
    pos: list, center_x: float, center_y: float, horizontal: bool
) -> list:
    n = len(pos) // 2
    if n < 1:
        return list(pos)
    result = list(pos)
    for i in range(n):
        if horizontal:
            result[i * 2] = (2.0 * center_x) - pos[i * 2]
        else:
            result[i * 2 + 1] = (2.0 * center_y) - pos[i * 2 + 1]
    return result


def mirror_position_coords(
    pos: list,
    center_x: float,
    center_y: float,
    horizontal: bool,
    *,
    is_curved: bool = False,
) -> list:
    result = mirror_points_around(pos, center_x, center_y, horizontal)
    if is_curved and len(result) >= 7:
        result[6] = -pos[6]
    return result
