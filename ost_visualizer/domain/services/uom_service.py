import math
from typing import List, Optional, Tuple
from ..entities.condition import Condition
from .dimension_format_service import MM_PER_INCH

UOM_EACH = 0
UOM_INCHES = 1
UOM_LINEAR_FEET = 2
UOM_LINEAR_YARDS = 3
UOM_SQUARE_INCHES = 4
UOM_SQUARE_FEET = 5
UOM_SQUARE_YARDS = 6
UOM_SQUARE_ROOFING = 7
UOM_CUBIC_FEET = 8
UOM_CUBIC_YARDS = 9
UOM_MM = 11
UOM_MM2 = 12
UOM_M = 13
UOM_M2 = 14
UOM_MM3 = 15
UOM_M3 = 16
CALC_TOP_BOTTOM = 5
CALC_TOP_AND_BOTTOM = 6
CALC_LINEAR_LENGTH = 1
CALC_LINEAR_BOTH_SIDES = 4
CALC_LINEAR_BOTH_ENDS = 8
CALC_AREA = 11
CALC_AREA_PERIMETER = 15
CALC_VOLUME = 20
CALC_AREA_VOLUME = 21
CALC_COUNT = 23
CALC_HEIGHT_OR_LENGTH = 24
CALC_WIDTH_SIDE = 25
CALC_BOTH_WIDTH_SIDES = 26
CALC_DEPTH_SIDE = 27
CALC_BOTH_DEPTH_SIDES = 28
CALC_ALL_SIDES = 29
CALC_ALL_SIDES_PLUS_TB = 30
UOM_LABELS = {
    UOM_EACH: "EA",
    UOM_INCHES: "IN",
    UOM_LINEAR_FEET: "LF",
    UOM_LINEAR_YARDS: "LY",
    UOM_SQUARE_INCHES: "SQ IN",
    UOM_SQUARE_FEET: "SF",
    UOM_SQUARE_YARDS: "SY",
    UOM_SQUARE_ROOFING: "ROOF",
    UOM_CUBIC_FEET: "CF",
    UOM_CUBIC_YARDS: "CY",
    UOM_MM: "MM",
    UOM_MM2: "MM²",
    UOM_M: "M",
    UOM_M2: "M²",
    UOM_MM3: "MM³",
    UOM_M3: "M³",
}
_METRIC_UOMS = frozenset({UOM_MM, UOM_MM2, UOM_M, UOM_M2, UOM_MM3, UOM_M3})


def get_uom_label(code: int) -> str:
    return UOM_LABELS.get(code, "")


def is_metric_uom(code: int) -> bool:
    return code in _METRIC_UOMS


COUNT_QUANTITY_OPTIONS: List[Tuple[int, str]] = [
    (CALC_COUNT, "Count"),
    (CALC_HEIGHT_OR_LENGTH, "Total Height"),
    (13, "Perimeter"),
    (CALC_TOP_BOTTOM, "Surface area (top or bottom)"),
    (CALC_TOP_AND_BOTTOM, "Surface area (top and bottom)"),
    (CALC_WIDTH_SIDE, "Surface area (single width side)"),
    (CALC_BOTH_WIDTH_SIDES, "Surface area (both width sides)"),
    (CALC_ALL_SIDES, "Surface area (all sides)"),
    (CALC_ALL_SIDES_PLUS_TB, "Surface area (all sides + top and bottom)"),
    (CALC_VOLUME, "Volume"),
]
LINEAR_QUANTITY_OPTIONS: List[Tuple[int, str]] = [
    (CALC_LINEAR_LENGTH, "Length"),
    (2, "Segment count"),
    (3, "Surface area (single side)"),
    (CALC_LINEAR_BOTH_SIDES, "Surface area (both sides)"),
    (CALC_TOP_BOTTOM, "Surface area (top or bottom)"),
    (CALC_TOP_AND_BOTTOM, "Surface area (top and bottom)"),
    (7, "Surface area (single end)"),
    (CALC_LINEAR_BOTH_ENDS, "Surface area (both ends)"),
    (9, "Surface area (all side/duct)"),
    (CALC_VOLUME, "Volume"),
]
AREA_QUANTITY_OPTIONS: List[Tuple[int, str]] = [
    (CALC_AREA, "Area"),
    (34, "Area (Ignore Backout Areas)"),
    (12, "Area (minus Attachments)"),
    (CALC_AREA_PERIMETER, "Perimeter"),
    (14, "Perimeter (without Backout Perimeters)"),
    (33, "Perimeter (plus Attachments Perimeter)"),
    (16, "Grid length (visible)"),
    (17, "Tile count (average)"),
    (18, "Tile count (visible)"),
    (19, "Area counts"),
    (CALC_AREA_VOLUME, "Volume"),
    (35, "Volume (Ignore Backout Volume)"),
    (22, "Volume (minus Attachments)"),
]
_COUNT_UOMS: List[Tuple[int, str]] = [(UOM_EACH, "EA")]
_LENGTH_UOMS: List[Tuple[int, str]] = [
    (UOM_LINEAR_FEET, "LF"),
    (UOM_LINEAR_YARDS, "LY"),
    (UOM_INCHES, "IN"),
]
_AREA_UOMS: List[Tuple[int, str]] = [
    (UOM_SQUARE_FEET, "SF"),
    (UOM_SQUARE_YARDS, "SY"),
    (UOM_SQUARE_INCHES, "SQ IN"),
]
_VOLUME_UOMS: List[Tuple[int, str]] = [
    (UOM_CUBIC_FEET, "CF"),
    (UOM_CUBIC_YARDS, "CY"),
]
_LENGTH_UOMS_METRIC: List[Tuple[int, str]] = [
    (UOM_M, "M"),
    (UOM_MM, "MM"),
]
_AREA_UOMS_METRIC: List[Tuple[int, str]] = [
    (UOM_M2, "M²"),
    (UOM_MM2, "MM²"),
]
_VOLUME_UOMS_METRIC: List[Tuple[int, str]] = [
    (UOM_M3, "M³"),
    (UOM_MM3, "MM³"),
]
_CALC_COUNT = {CALC_COUNT, 2, 17, 18, 19}
_CALC_LENGTH = {
    CALC_LINEAR_LENGTH,
    CALC_HEIGHT_OR_LENGTH,
    13,
    14,
    CALC_AREA_PERIMETER,
    16,
    33,
}
_CALC_AREA = {
    CALC_TOP_BOTTOM,
    CALC_TOP_AND_BOTTOM,
    CALC_WIDTH_SIDE,
    CALC_BOTH_WIDTH_SIDES,
    CALC_DEPTH_SIDE,
    CALC_BOTH_DEPTH_SIDES,
    CALC_ALL_SIDES,
    CALC_ALL_SIDES_PLUS_TB,
    3,
    CALC_LINEAR_BOTH_SIDES,
    7,
    CALC_LINEAR_BOTH_ENDS,
    9,
    CALC_AREA,
    12,
    34,
}
_CALC_VOLUME = {CALC_VOLUME, CALC_AREA_VOLUME, 22, 35}


def get_valid_uoms_for_calc_type(
    calc_type: int, metric: bool = False
) -> List[Tuple[int, str]]:
    if calc_type in _CALC_COUNT or calc_type == 0:
        return _COUNT_UOMS
    if calc_type in _CALC_LENGTH:
        return _LENGTH_UOMS_METRIC if metric else _LENGTH_UOMS
    if calc_type in _CALC_VOLUME:
        return _VOLUME_UOMS_METRIC if metric else _VOLUME_UOMS
    if calc_type in _CALC_AREA:
        return _AREA_UOMS_METRIC if metric else _AREA_UOMS
    return _LENGTH_UOMS_METRIC if metric else _LENGTH_UOMS


def get_quantity_options_for_type(
    condition_type: int,
) -> List[Tuple[int, str]]:
    if condition_type == Condition.TYPE_COUNT:
        return COUNT_QUANTITY_OPTIONS
    if condition_type == Condition.TYPE_LINEAR:
        return LINEAR_QUANTITY_OPTIONS
    if condition_type == Condition.TYPE_AREA:
        return AREA_QUANTITY_OPTIONS
    return COUNT_QUANTITY_OPTIONS


_MM2_PER_SQIN = MM_PER_INCH * MM_PER_INCH
_MM3_PER_CUIN = _MM2_PER_SQIN * MM_PER_INCH
_UOM_DIVISORS = {
    UOM_EACH: 1.0,
    UOM_INCHES: 1.0,
    UOM_LINEAR_FEET: 12.0,
    UOM_LINEAR_YARDS: 36.0,
    UOM_SQUARE_INCHES: 1.0,
    UOM_SQUARE_FEET: 144.0,
    UOM_SQUARE_YARDS: 1296.0,
    UOM_SQUARE_ROOFING: 14400.0,
    UOM_CUBIC_FEET: 1728.0,
    UOM_CUBIC_YARDS: 46656.0,
    UOM_MM: 1.0 / MM_PER_INCH,
    UOM_M: 1000.0 / MM_PER_INCH,
    UOM_MM2: 1.0 / _MM2_PER_SQIN,
    UOM_M2: 1_000_000.0 / _MM2_PER_SQIN,
    UOM_MM3: 1.0 / _MM3_PER_CUIN,
    UOM_M3: 1_000_000_000.0 / _MM3_PER_CUIN,
}


def calculate_net_area_sf(
    position: List[float],
    hole_positions: Optional[List[List[float]]] = None,
) -> float:
    area_sq_in = _calc_polygon_area_sq_inches(position)
    if hole_positions:
        for hp in hole_positions:
            area_sq_in -= _calc_polygon_area_sq_inches(hp)
    return convert_to_uom(max(0.0, area_sq_in), UOM_SQUARE_FEET)


def vertices_from_position(position: List[float]) -> List[Tuple[float, float]]:
    vertices = []
    for i in range(0, len(position) - 1, 2):
        vertices.append((position[i], position[i + 1]))
    return vertices


def calculate_polygon_area(vertices: List[Tuple[float, float]]) -> float:
    n = len(vertices)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += vertices[i][0] * vertices[j][1] - vertices[j][0] * vertices[i][1]
    return abs(area) / 2.0


_UOM_IMPERIAL_TO_METRIC = {
    UOM_INCHES: UOM_M,
    UOM_LINEAR_FEET: UOM_M,
    UOM_LINEAR_YARDS: UOM_M,
    UOM_SQUARE_INCHES: UOM_M2,
    UOM_SQUARE_FEET: UOM_M2,
    UOM_SQUARE_YARDS: UOM_M2,
    UOM_SQUARE_ROOFING: UOM_M2,
    UOM_CUBIC_FEET: UOM_M3,
    UOM_CUBIC_YARDS: UOM_M3,
}
_UOM_METRIC_TO_IMPERIAL = {
    UOM_MM: UOM_LINEAR_FEET,
    UOM_M: UOM_LINEAR_FEET,
    UOM_MM2: UOM_SQUARE_FEET,
    UOM_M2: UOM_SQUARE_FEET,
    UOM_MM3: UOM_CUBIC_FEET,
    UOM_M3: UOM_CUBIC_FEET,
}


def normalize_uom_for_system(uom_code: int, metric: bool) -> int:
    if metric:
        return _UOM_IMPERIAL_TO_METRIC.get(uom_code, uom_code)
    return _UOM_METRIC_TO_IMPERIAL.get(uom_code, uom_code)


def convert_to_uom(raw_value: float, uom_code: int) -> float:
    divisor = _UOM_DIVISORS.get(uom_code, 1.0)
    if divisor == 0:
        return 0.0
    return raw_value / divisor


def convert_and_round_quantity(
    raw_value: float,
    uom_code: int,
    round_quantity: bool = False,
    round_up: float = 0.0,
) -> float:
    value = convert_to_uom(raw_value, uom_code)
    if round_quantity and round_up > 0:
        increment = convert_to_uom(round_up, uom_code)
        if increment > 0:
            value = math.ceil(value / increment) * increment
    return value


def _calc_raw_for_count(
    calc_type: int,
    width: float,
    height: float,
    depth: float,
) -> float:
    if calc_type == 13:
        return 2.0 * (width + depth)
    if calc_type == CALC_COUNT:
        return 1.0
    if calc_type == CALC_HEIGHT_OR_LENGTH:
        return height
    if calc_type == CALC_TOP_BOTTOM:
        return width * depth
    if calc_type == CALC_TOP_AND_BOTTOM:
        return 2.0 * width * depth
    if calc_type == CALC_VOLUME:
        return width * depth * height
    if calc_type == CALC_WIDTH_SIDE:
        return width * height
    if calc_type == CALC_BOTH_WIDTH_SIDES:
        return 2.0 * width * height
    if calc_type == CALC_DEPTH_SIDE:
        return depth * height
    if calc_type == CALC_BOTH_DEPTH_SIDES:
        return 2.0 * depth * height
    if calc_type == CALC_ALL_SIDES:
        return 2.0 * (width * height + depth * height)
    if calc_type == CALC_ALL_SIDES_PLUS_TB:
        return 2.0 * (width * height + depth * height + width * depth)
    return 0.0


def _perp_slope(dx: float, dy: float) -> float:
    if dy == 0.0:
        return math.inf
    if dx == 0.0:
        return 0.0
    return -dx / dy


def _quadratic_curve_points(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    cx: float,
    cy: float,
    segments: int,
) -> List[Tuple[float, float]]:
    points = []
    for i in range(segments + 1):
        t = i / segments
        u = 1.0 - t
        points.append(
            (
                u * u * x1 + 2.0 * u * t * cx + t * t * x2,
                u * u * y1 + 2.0 * u * t * cy + t * t * y2,
            )
        )
    return points


def _process_curved_position(position: List[float]) -> Tuple[float, ...]:
    x1, y1, x2, y2, cx, cy = position[:6]
    if len(position) >= 7:
        offset = -position[6]
        mid_x = (x1 + x2) * 0.5
        mid_y = (y1 + y2) * 0.5
        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        if length > 0.0:
            dx /= length
            dy /= length
            cx = mid_x - dy * offset
            cy = mid_y + dx * offset
    return x1, y1, x2, y2, cx, cy


def _calc_curve_segments(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    cx: float,
    cy: float,
) -> int:
    chord_d = math.hypot(x2 - x1, y2 - y1)
    curve_d = (math.hypot(cx - x1, cy - y1) + math.hypot(x2 - cx, y2 - cy)) * 0.8
    base = max(6, min(64, int(max(chord_d, curve_d) / 5.0)))
    if chord_d > 0.0:
        dx = x2 - x1
        dy = y2 - y1
        t = ((cx - x1) * dx + (cy - y1) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        offset = math.hypot(cx - (x1 + t * dx), cy - (y1 + t * dy))
        base += int(offset / 5.0)
    return max(6, min(64, base))


def _advanced_curve_points(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    cx: float,
    cy: float,
    segments: int,
) -> List[Tuple[float, float]]:
    mid1_x = (x1 + cx) * 0.5
    mid1_y = (y1 + cy) * 0.5
    mid2_x = (cx + x2) * 0.5
    mid2_y = (cy + y2) * 0.5
    slope1 = _perp_slope(cx - x1, cy - y1)
    slope2 = _perp_slope(x2 - cx, y2 - cy)
    found = False
    center_x = 0.0
    center_y = 0.0
    if math.isinf(slope1):
        if not math.isinf(slope2):
            center_x = mid1_x
            center_y = mid2_y + slope2 * (mid1_x - mid2_x)
            found = True
    elif math.isinf(slope2):
        center_x = mid2_x
        center_y = mid1_y + slope1 * (mid2_x - mid1_x)
        found = True
    elif abs(slope1 - slope2) > 1e-10:
        center_x = (mid2_y - mid1_y + slope1 * mid1_x - slope2 * mid2_x) / (
            slope1 - slope2
        )
        center_y = mid1_y + slope1 * (center_x - mid1_x)
        found = True
    if found:
        radius1 = math.hypot(center_x - x1, center_y - y1)
        radius2 = math.hypot(center_x - x2, center_y - y2)
        radius_c = math.hypot(center_x - cx, center_y - cy)
        if abs(radius1 - radius2) < 0.1 and abs(radius1 - radius_c) < 0.1:
            start_angle = math.atan2(y1 - center_y, x1 - center_x)
            end_angle = math.atan2(y2 - center_y, x2 - center_x)
            cross1 = (x1 - center_x) * (cy - center_y) - (y1 - center_y) * (
                cx - center_x
            )
            cross2 = (cx - center_x) * (y2 - center_y) - (cy - center_y) * (
                x2 - center_x
            )
            clockwise = (cross1 + cross2) < 0.0
            if clockwise and end_angle > start_angle:
                end_angle -= 2.0 * math.pi
            elif not clockwise and end_angle < start_angle:
                end_angle += 2.0 * math.pi
            angle_diff = end_angle - start_angle
            return [
                (
                    center_x
                    + radius1 * math.cos(start_angle + (i / segments) * angle_diff),
                    center_y
                    + radius1 * math.sin(start_angle + (i / segments) * angle_diff),
                )
                for i in range(segments + 1)
            ]
    return _quadratic_curve_points(x1, y1, x2, y2, cx, cy, segments)


def _calc_curved_linear_length(position: List[float]) -> float:
    x1, y1, x2, y2, cx, cy = _process_curved_position(position)
    points = _advanced_curve_points(
        x1,
        y1,
        x2,
        y2,
        cx,
        cy,
        _calc_curve_segments(x1, y1, x2, y2, cx, cy),
    )
    return sum(
        math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
        for i in range(len(points) - 1)
    )


def _calc_linear_length(position: List[float], curve: int = -1) -> float:
    if len(position) < 4:
        return 0.0
    if curve >= 0 and len(position) >= 6:
        return _calc_curved_linear_length(position)
    total_length = 0.0
    segment_stride = 7
    i = 0
    while i + 3 < len(position):
        x1, y1 = position[i], position[i + 1]
        x2, y2 = position[i + 2], position[i + 3]
        dx = x2 - x1
        dy = y2 - y1
        total_length += math.sqrt(dx * dx + dy * dy)
        i += segment_stride
    return total_length


def _calc_raw_for_linear(
    calc_type: int,
    height: float,
    thickness: float,
    length_inches: float,
) -> float:
    if calc_type == 0:
        return 0.0
    if calc_type == CALC_LINEAR_LENGTH:
        return length_inches
    if calc_type == 2:
        return 1.0
    if calc_type == 3:
        return length_inches * height
    if calc_type == CALC_LINEAR_BOTH_SIDES:
        return 2.0 * length_inches * height
    if calc_type == 5:
        return length_inches * thickness
    if calc_type == 6:
        return 2.0 * length_inches * thickness
    if calc_type == 7:
        return thickness * height
    if calc_type == CALC_LINEAR_BOTH_ENDS:
        return 2.0 * thickness * height
    if calc_type == 9:
        return 2.0 * length_inches * (height + thickness)
    if calc_type == 20:
        return length_inches * height * thickness
    return 0.0


def _calc_polygon_area_sq_inches(position: List[float]) -> float:
    vertices = vertices_from_position(position)
    if len(vertices) < 3:
        return 0.0
    return calculate_polygon_area(vertices)


def _calc_polygon_perimeter(position: List[float]) -> float:
    vertices = vertices_from_position(position)
    n = len(vertices)
    if n < 2:
        return 0.0
    perimeter = 0.0
    for i in range(n):
        j = (i + 1) % n
        dx = vertices[j][0] - vertices[i][0]
        dy = vertices[j][1] - vertices[i][1]
        perimeter += math.sqrt(dx * dx + dy * dy)
    return perimeter


def calculate_bounding_box_inches(position: List[float]) -> Tuple[float, float]:
    vertices = vertices_from_position(position)
    if not vertices:
        return (0.0, 0.0)
    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    return (max(xs) - min(xs), max(ys) - min(ys))


def _calc_raw_for_area(
    calc_type: int,
    thickness: float,
    polygon_area: float,
    hole_area: float,
    polygon_perimeter: float,
    hole_perimeter: float,
    attachment_footprint: float,
    attachment_perimeter: float,
    grid_size1: float = 0.0,
    grid_size2: float = 0.0,
    gap: float = 0.0,
    bbox_w: float = 0.0,
    bbox_h: float = 0.0,
) -> float:
    net_area = polygon_area - hole_area
    if calc_type == 0:
        return 0.0
    if calc_type == CALC_AREA:
        return net_area
    if calc_type == 12:
        return net_area - attachment_footprint
    if calc_type == 14:
        return polygon_perimeter
    if calc_type == CALC_AREA_PERIMETER:
        return polygon_perimeter + hole_perimeter
    if calc_type == 16:
        unit1 = grid_size1 + gap
        unit2 = grid_size2 + gap
        if unit1 <= 0 or unit2 <= 0:
            return 0.0
        return math.ceil(bbox_w / unit1) * bbox_h + math.ceil(bbox_h / unit2) * bbox_w
    if calc_type == 17:
        unit1 = grid_size1 + gap
        unit2 = grid_size2 + gap
        if unit1 <= 0 or unit2 <= 0:
            return 0.0
        return net_area / (unit1 * unit2)
    if calc_type == 18:
        unit1 = grid_size1 + gap
        unit2 = grid_size2 + gap
        if unit1 <= 0 or unit2 <= 0:
            return 0.0
        return math.floor(bbox_w / unit1) * math.floor(bbox_h / unit2)
    if calc_type == 19:
        return 1.0
    if calc_type == CALC_AREA_VOLUME:
        return net_area * thickness
    if calc_type == 22:
        return (net_area - attachment_footprint) * thickness
    if calc_type == 23:
        return 1.0
    if calc_type == 33:
        return polygon_perimeter + hole_perimeter + attachment_perimeter
    if calc_type == 34:
        return polygon_area
    if calc_type == 35:
        return polygon_area * thickness
    return 0.0


def _calc_slope_factor(rise: float, run: float, use_absolute: bool = False) -> float:
    if use_absolute:
        rise = abs(rise)
        run = abs(run)
    if run > 0.0 and rise > 0.0:
        return math.sqrt(rise * rise + run * run) / run
    return 1.0


def calculate_condition_quantities(
    condition_type: int,
    calc_type1: int,
    calc_type2: int,
    calc_type3: int,
    uom1: int,
    uom2: int,
    uom3: int,
    width: float,
    height: float,
    depth: float,
    thickness: float,
    position: Optional[List[float]] = None,
    hole_positions: Optional[List[List[float]]] = None,
    attachment_footprint: float = 0.0,
    attachment_perimeter: float = 0.0,
    rise: float = 0.0,
    run: float = 0.0,
    grid_size1: float = 0.0,
    grid_size2: float = 0.0,
    gap: float = 0.0,
    curve: int = -1,
    round_quantity: bool = False,
    round_up: float = 0.0,
) -> Tuple[float, float, float]:
    pos = position or []
    slope = _calc_slope_factor(
        rise,
        run,
        use_absolute=condition_type == Condition.TYPE_AREA,
    )
    if condition_type == Condition.TYPE_LINEAR:
        length_inches = _calc_linear_length(pos, curve) * slope
    elif condition_type == Condition.TYPE_AREA:
        polygon_area = _calc_polygon_area_sq_inches(pos) * slope
        polygon_perimeter = _calc_polygon_perimeter(pos) * slope
        bbox_w, bbox_h = calculate_bounding_box_inches(pos)
        hole_area = 0.0
        hole_perim = 0.0
        if hole_positions:
            for hp in hole_positions:
                hole_area += _calc_polygon_area_sq_inches(hp) * slope
                hole_perim += _calc_polygon_perimeter(hp) * slope
    results = []
    for calc_type, uom in ((calc_type1, uom1), (calc_type2, uom2), (calc_type3, uom3)):
        if condition_type in (Condition.TYPE_COUNT, Condition.TYPE_ATTACHMENT):
            raw = _calc_raw_for_count(calc_type, width, height, depth)
        elif condition_type == Condition.TYPE_LINEAR:
            raw = _calc_raw_for_linear(calc_type, height, thickness, length_inches)
        else:
            raw = _calc_raw_for_area(
                calc_type,
                thickness,
                polygon_area,
                hole_area,
                polygon_perimeter,
                hole_perim,
                attachment_footprint,
                attachment_perimeter,
                grid_size1,
                grid_size2,
                gap,
                bbox_w,
                bbox_h,
            )
        results.append(
            convert_and_round_quantity(
                raw,
                uom,
                round_quantity=round_quantity,
                round_up=round_up,
            )
        )
    return (results[0], results[1], results[2])
