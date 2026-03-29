import math
from dataclasses import dataclass

SQUARE = 0
CIRCLE = 1
TRIANGLE = 2
RECTANGLE = 3
RHOMBUS = 12
ELLIPSE = 13
HEXAGON = 14
OCTAGON = 15
POLYGON_SHAPES: dict[int, tuple[int, float]] = {
    TRIANGLE: (3, math.pi / 6),
    HEXAGON: (6, 0),
    OCTAGON: (8, math.pi / 8),
}
ELLIPSE_SHAPES = frozenset({CIRCLE, ELLIPSE})


@dataclass(frozen=True)
class ShapeSpec:
    shape_id: int
    width: float
    depth: float
    rotation: float = 0.0

    @property
    def is_ellipse(self) -> bool:
        return self.shape_id in ELLIPSE_SHAPES

    @property
    def is_polygon(self) -> bool:
        return self.shape_id in POLYGON_SHAPES

    @property
    def polygon_params(self) -> tuple[int, float] | None:
        return POLYGON_SHAPES.get(self.shape_id)

    @property
    def half_width(self) -> float:
        return self.width / 2

    @property
    def half_depth(self) -> float:
        return self.depth / 2


def create_polygon_points(
    center_x: float,
    center_y: float,
    half_width: float,
    sides: int,
    angle_offset: float,
    rotation: float = 0.0,
    half_depth: float | None = None,
) -> list[tuple[float, float]]:
    points = []
    ry = half_depth if half_depth is not None else half_width
    for i in range(sides):
        angle = angle_offset + i * 2 * math.pi / sides + rotation
        x = center_x + half_width * math.cos(angle)
        y = center_y + ry * math.sin(angle)
        points.append((x, y))
    return points


def create_isosceles_triangle_points(
    center_x: float,
    center_y: float,
    half_width: float,
    half_depth: float,
    rotation: float = 0.0,
) -> list[tuple[float, float]]:
    corners = [
        (0, -half_depth),
        (half_width, half_depth),
        (-half_width, half_depth),
    ]
    if rotation:
        cos_r, sin_r = math.cos(rotation), math.sin(rotation)
        rotated = []
        for px, py in corners:
            rx = px * cos_r - py * sin_r
            ry = px * sin_r + py * cos_r
            rotated.append((center_x + rx, center_y + ry))
        return rotated
    return [(center_x + px, center_y + py) for px, py in corners]


def create_rhombus_points(
    center_x: float,
    center_y: float,
    half_width: float,
    half_depth: float | None = None,
    rotation: float = 0.0,
) -> list[tuple[float, float]]:
    horizontal_scale = 0.575
    corners = [
        (0, -half_width),
        (half_width * horizontal_scale, 0),
        (0, half_width),
        (-half_width * horizontal_scale, 0),
    ]
    if rotation:
        cos_r, sin_r = math.cos(rotation), math.sin(rotation)
        rotated = []
        for px, py in corners:
            rx = px * cos_r - py * sin_r
            ry = px * sin_r + py * cos_r
            rotated.append((center_x + rx, center_y + ry))
        return rotated
    return [(center_x + px, center_y + py) for px, py in corners]


def create_rectangle_points(
    center_x: float,
    center_y: float,
    half_width: float,
    half_depth: float,
    rotation: float = 0.0,
) -> list[tuple[float, float]]:
    corners = [
        (-half_width, -half_depth),
        (half_width, -half_depth),
        (half_width, half_depth),
        (-half_width, half_depth),
    ]
    if rotation:
        cos_r, sin_r = math.cos(rotation), math.sin(rotation)
        rotated = []
        for px, py in corners:
            rx = px * cos_r - py * sin_r
            ry = px * sin_r + py * cos_r
            rotated.append((center_x + rx, center_y + ry))
        return rotated
    return [(center_x + px, center_y + py) for px, py in corners]
