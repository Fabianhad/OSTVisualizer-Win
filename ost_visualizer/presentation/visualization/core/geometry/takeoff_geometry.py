import math
from typing import List, Optional, Tuple
from .....domain.entities import shape as shapes


def compute_straight_linear_vertices(
    x1: float, y1: float, x2: float, y2: float, thickness: float
) -> Optional[List[Tuple[float, float]]]:
    dx, dy = x2 - x1, y2 - y1
    length = math.sqrt(dx * dx + dy * dy)
    if length < 0.001:
        return None
    dx_n, dy_n = dx / length, dy / length
    half_t = thickness / 2.0
    px, py = -dy_n * half_t, dx_n * half_t
    return [
        (x1 + px, y1 + py),
        (x1 - px, y1 - py),
        (x2 - px, y2 - py),
        (x2 + px, y2 + py),
    ]


def compute_line_angle(x1: float, y1: float, x2: float, y2: float) -> Optional[float]:
    dx, dy = x2 - x1, y2 - y1
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return None
    return math.atan2(dy, dx)


def compute_curved_linear_vertices(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    cx: float,
    cy: float,
    gen_curve_pts_fn,
    gen_thick_curve_offsets_fn,
    thickness: float,
    num_segments: int = 24,
) -> Optional[List[Tuple[float, float]]]:
    curve_pts = gen_curve_pts_fn(x1, y1, x2, y2, cx, cy, num_segments)
    if len(curve_pts) < 2:
        return None
    inner, outer = gen_thick_curve_offsets_fn(curve_pts, thickness)
    vertices = list(inner)
    vertices.extend(reversed(outer))
    return vertices


def compute_count_vertices(
    cx: float,
    cy: float,
    shape_id: int,
    width: float,
    depth: float,
    rotation: float = 0.0,
) -> List[Tuple[float, float]]:
    half_w = width / 2.0
    half_d = depth / 2.0
    spec = shapes.ShapeSpec(shape_id, width, depth, rotation)
    if spec.is_ellipse:
        return shapes.create_polygon_points(cx, cy, half_w, 32, 0, rotation, half_d)
    if shape_id == shapes.TRIANGLE:
        return shapes.create_isosceles_triangle_points(cx, cy, half_w, half_d, rotation)
    if shape_id == shapes.RHOMBUS:
        return shapes.create_rhombus_points(cx, cy, half_w, rotation=rotation)
    if spec.is_polygon:
        params = spec.polygon_params
        points = shapes.create_polygon_points(
            0, 0, half_w, params[0], params[1], rotation
        )
        return [(cx + px, cy + py) for px, py in points]
    points = shapes.create_rectangle_points(0, 0, half_w, half_d, rotation)
    return [(cx + px, cy + py) for px, py in points]
