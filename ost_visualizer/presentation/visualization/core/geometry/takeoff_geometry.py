import math
from typing import List, Optional, Tuple
from .....application.interfaces.i_linear_geometry import ILinearGeometry
from .....domain.entities import shape as shapes
from .....domain.entities.condition import Condition
from .....domain.entities.takeoff import Takeoff

MINIMUM_RENDERED_POINT_TAKEOFF_SIZE = 8.0
MINIMUM_RENDERED_LINEAR_THICKNESS = 2.0


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


def resolve_point_takeoff_shape(
    condition: Condition,
) -> Tuple[int, float, float]:
    shape_id = condition.shape
    width = max(condition.width if condition.width else 1.0, 1.0)
    if shape_id in (shapes.SQUARE, shapes.CIRCLE):
        depth = width
    else:
        depth = max(condition.depth if condition.depth else width, 1.0)
    if condition.is_count:
        display_scale = max(condition.display_size, 0.1) / 100.0
        width *= display_scale
        depth *= display_scale
    return shape_id, width, depth


def apply_minimum_point_takeoff_size(
    width: float,
    depth: float,
    minimum_dimension: float,
) -> Tuple[float, float]:
    smaller_dimension = min(width, depth)
    if smaller_dimension < minimum_dimension:
        scale = minimum_dimension / smaller_dimension
        return width * scale, depth * scale
    return width, depth


def compute_takeoff_footprint_vertices(
    takeoff: Takeoff,
    condition: Condition,
    linear_geometry: ILinearGeometry,
    minimum_point_dimension: float,
    minimum_linear_thickness: float,
) -> List[Tuple[float, float]]:
    position = takeoff.position
    if condition.is_area:
        if len(position) < 6 or len(position) % 2:
            return []
        return list(zip(position[0::2], position[1::2]))
    if condition.is_linear:
        if len(position) < 4:
            return []
        thickness = max(
            condition.thickness if condition.thickness else 1.0,
            minimum_linear_thickness,
        )
        if takeoff.curve >= 0 and len(position) >= 6:
            x1, y1, x2, y2, cx, cy = linear_geometry.proc_curved_pos(
                position,
                position[0],
                position[1],
                position[2],
                position[3],
                position[4],
                position[5],
            )
            return (
                compute_curved_linear_vertices(
                    x1,
                    y1,
                    x2,
                    y2,
                    cx,
                    cy,
                    linear_geometry.gen_curve_pts,
                    linear_geometry.gen_thick_curve_offsets,
                    thickness,
                )
                or []
            )
        return (
            compute_straight_linear_vertices(
                position[0],
                position[1],
                position[2],
                position[3],
                thickness,
            )
            or []
        )
    if condition.is_count or condition.is_attachment:
        if len(position) < 2:
            return []
        shape_id, width, depth = resolve_point_takeoff_shape(condition)
        width, depth = apply_minimum_point_takeoff_size(
            width,
            depth,
            minimum_point_dimension,
        )
        return compute_count_vertices(
            position[0],
            position[1],
            shape_id,
            width,
            depth,
            takeoff.rotation,
        )
    return []


def compute_takeoff_footprint_bounds(
    takeoff: Takeoff,
    condition: Condition,
    linear_geometry: ILinearGeometry,
    minimum_point_dimension: float,
    minimum_linear_thickness: float,
) -> Optional[Tuple[float, float, float, float]]:
    vertices = compute_takeoff_footprint_vertices(
        takeoff,
        condition,
        linear_geometry,
        minimum_point_dimension,
        minimum_linear_thickness,
    )
    if not vertices:
        return None
    xs = [point[0] for point in vertices]
    ys = [point[1] for point in vertices]
    return min(xs), min(ys), max(xs), max(ys)


def mirror_point_takeoff_rotation(rotation: float, horizontal: bool) -> float:
    if horizontal:
        return -rotation
    return math.pi - rotation
