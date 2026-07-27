import math
from typing import Any, Dict, List, Optional, Tuple
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
    BidAnnotation,
)
from .....domain.entities.hotlink import build_hotlink_from_annotation
from .....domain.services.dimension_format_service import inches_to_display

Point = Tuple[float, float]
Segment = Tuple[float, float, float, float]
CLOUD_SCALLOP_MIN_RADIUS = 15.0
CLOUD_SCALLOP_MAX_RADIUS = 50.0
CLOUD_SCALLOP_SIZE_SCALE = 0.25


def create_cloud_path_points(
    points: List[Point], intensity: float = 2.0
) -> List[Tuple[Point, Point, Point]]:
    if len(points) < 2:
        return []
    pts = list(points)
    if abs(pts[0][0] - pts[-1][0]) > 1e-6 or abs(pts[0][1] - pts[-1][1]) > 1e-6:
        pts.append(pts[0])
    pts = _ensure_clockwise(pts)
    edges = _polygon_perimeter_edges(pts)
    if not edges:
        return []
    avg_e = sum(e[2] for e in edges) / len(edges)
    cloud_radius = calculate_cloud_scallop_radius(avg_e, intensity)
    perimeter = sum(e[2] for e in edges)
    step = 3.25 * cloud_radius
    n_samples = max(6, int(math.ceil(perimeter / step)))
    cloudy_bases = _sample_along_perimeter(pts, n_samples)
    if len(cloudy_bases) < 2:
        return []
    centers = _compute_centers_from_samples(cloudy_bases, cloud_radius, invert=False)
    segments = []
    n = len(cloudy_bases)
    for k in range(n):
        start = cloudy_bases[k]
        end = cloudy_bases[(k + 1) % n]
        center = centers[(k + 1) % n]
        r = _length(center, start)
        a_start = math.atan2(start[1] - center[1], start[0] - center[0])
        a_end = math.atan2(end[1] - center[1], end[0] - center[0])
        while a_end < a_start:
            a_end += 2 * math.pi
        if a_end - a_start > math.pi:
            a_end -= 2 * math.pi
        bezier_segments = _arc_to_bezier(center, r, a_start, a_end)
        for cp1, cp2, pt in bezier_segments:
            segments.append((start if k == 0 else None, cp1, cp2, pt))
    return segments


def calculate_cloud_scallop_radius(avg_edge_length: float, intensity: float) -> float:
    base_radius = max(
        CLOUD_SCALLOP_MIN_RADIUS,
        min(avg_edge_length * intensity / 3, CLOUD_SCALLOP_MAX_RADIUS),
    )
    return base_radius * CLOUD_SCALLOP_SIZE_SCALE


def process_text_for_box(
    text_content: str,
    box_width: float,
    box_height: float,
    font_metrics: Any,
    ellipsis: str = "...",
) -> str:
    if not text_content:
        return ""
    ellipsis_width = font_metrics.horizontalAdvance(ellipsis)
    words = text_content.split(" ")
    processed_words = []
    for word in words:
        word_width = font_metrics.horizontalAdvance(word)
        if word_width > box_width:
            available_width = box_width - ellipsis_width
            low, high = 0, len(word)
            while low < high:
                mid = (low + high + 1) // 2
                if font_metrics.horizontalAdvance(word[:mid]) <= available_width:
                    low = mid
                else:
                    high = mid - 1
            processed_words.append(word[:low] + ellipsis)
        else:
            processed_words.append(word)
    return " ".join(processed_words)


def format_dimension_distance(distance_inches: float) -> str:
    display = inches_to_display(distance_inches, metric=False)
    if not display:
        return ""
    if "'" not in display:
        return display
    feet_part, inch_part = display.split("'", 1)
    inch_part = inch_part.strip()
    if not inch_part:
        return f"{feet_part}'"
    return f"{feet_part}' - {inch_part}"


def calculate_dimension_segments(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    tick_length: float,
) -> List[Segment]:
    length = math.hypot(x2 - x1, y2 - y1)
    if length <= 1e-9:
        return []
    nx = -(y2 - y1) / length
    ny = (x2 - x1) / length
    half_tick = tick_length / 2.0
    return [
        (x1, y1, x2, y2),
        (
            x1 - nx * half_tick,
            y1 - ny * half_tick,
            x1 + nx * half_tick,
            y1 + ny * half_tick,
        ),
        (
            x2 - nx * half_tick,
            y2 - ny * half_tick,
            x2 + nx * half_tick,
            y2 + ny * half_tick,
        ),
    ]


def calculate_dimension_geometry(
    annotation: BidAnnotation,
    position: List[float],
    transform_func,
) -> Optional[Dict[str, Any]]:
    if len(position) < 4:
        return None
    tx_position = transform_func(position)
    if len(tx_position) < 4:
        return None
    distance = math.hypot(position[2] - position[0], position[3] - position[1])
    return {
        "x1": tx_position[0],
        "y1": tx_position[1],
        "x2": tx_position[2],
        "y2": tx_position[3],
        "label": format_dimension_distance(distance),
        "font_name": annotation.properties.get("FontName", "Arial"),
        "font_size": annotation.properties.get("FontSize", 10),
        "font_bold": annotation.properties.get("FontBold", False),
        "font_italic": annotation.properties.get("FontItalic", False),
        "font_underline": annotation.properties.get("FontUnderline", False),
    }


def calculate_annotation_geometry(
    annotation: BidAnnotation,
    transform_func,
) -> Optional[Dict[str, Any]]:
    position = annotation.position
    if not position:
        return None
    anno_type = annotation.annotation_type
    tx_position = transform_func(position)
    result = {
        "type": anno_type,
        "color": annotation.color,
        "width": annotation.width,
        "transformed_position": tx_position,
    }
    if anno_type in (
        ANNOTATION_TYPE_CLOUD,
        ANNOTATION_TYPE_POLYGON,
        ANNOTATION_TYPE_INK,
    ):
        if anno_type == ANNOTATION_TYPE_INK:
            start = 1 if len(position) % 2 == 1 else 0
            coords = position[start:]
            tx_ink = transform_func(coords)
            points = [(tx_ink[i], tx_ink[i + 1]) for i in range(0, len(tx_ink) - 1, 2)]
        else:
            points = [
                (tx_position[i], tx_position[i + 1])
                for i in range(0, len(tx_position) - 1, 2)
            ]
        result["points"] = points
    elif anno_type in (
        ANNOTATION_TYPE_OVAL,
        ANNOTATION_TYPE_RECT,
        ANNOTATION_TYPE_HIGHLIGHT,
    ):
        if len(position) >= 4:
            has_rotation = len(position) % 2 == 1
            n_coords = len(position) - 1 if has_rotation else len(position)
            tx_coords = transform_func(position[:n_coords])
            points = [
                (tx_coords[i], tx_coords[i + 1])
                for i in range(0, len(tx_coords) - 1, 2)
            ]
            if anno_type == ANNOTATION_TYPE_OVAL:
                if len(points) >= 2:
                    cx = (points[0][0] + points[1][0]) / 2
                    cy = (points[0][1] + points[1][1]) / 2
                    stored_rad = position[-1] if has_rotation else 0.0
                    cos_r, sin_r = math.cos(stored_rad), math.sin(stored_rad)
                    unrot = []
                    for p in points[:2]:
                        dx, dy = p[0] - cx, p[1] - cy
                        unrot.append(
                            (cx + dx * cos_r + dy * sin_r, cy - dx * sin_r + dy * cos_r)
                        )
                    w = abs(unrot[1][0] - unrot[0][0])
                    h = abs(unrot[1][1] - unrot[0][1])
                    result["oval"] = {
                        "cx": cx,
                        "cy": cy,
                        "w": w,
                        "h": h,
                        "rotation_deg": math.degrees(stored_rad),
                    }
            elif len(points) >= 4:
                rotation_deg = math.degrees(position[-1]) if has_rotation else 0.0
                result["shape"] = {
                    "corners": points[:4],
                    "rotation": rotation_deg,
                }
            elif len(points) >= 2:
                result["bounds"] = {
                    "min_x": min(p[0] for p in points),
                    "max_x": max(p[0] for p in points),
                    "min_y": min(p[1] for p in points),
                    "max_y": max(p[1] for p in points),
                }
    elif anno_type in (ANNOTATION_TYPE_LINE, ANNOTATION_TYPE_ARROW):
        if len(tx_position) >= 4:
            result["line"] = {
                "x1": tx_position[0],
                "y1": tx_position[1],
                "x2": tx_position[2],
                "y2": tx_position[3],
            }
    elif anno_type == ANNOTATION_TYPE_DIMENSION:
        dimension = calculate_dimension_geometry(annotation, position, transform_func)
        if dimension:
            result["dimension"] = dimension
    elif anno_type == ANNOTATION_TYPE_TEXT:
        if len(position) >= 4:
            result["text"] = {
                "content": annotation.properties.get("Text", ""),
                "center_x": position[0],
                "center_y": position[1],
                "box_width": position[2],
                "box_height": position[3],
                "rotation": math.degrees(position[4]) if len(position) >= 5 else 0,
                "font_name": annotation.properties.get("FontName", "Arial"),
                "font_size": annotation.properties.get("FontSize", 12),
                "font_bold": annotation.properties.get("FontBold", False),
                "font_italic": annotation.properties.get("FontItalic", False),
                "font_underline": annotation.properties.get("FontUnderline", False),
                "text_align": annotation.properties.get("TextAlign", 0),
            }
    elif anno_type == ANNOTATION_TYPE_NAMED_VIEW:
        if len(tx_position) >= 8:
            points = [(tx_position[i], tx_position[i + 1]) for i in range(0, 8, 2)]
            min_x = min(p[0] for p in points)
            max_x = max(p[0] for p in points)
            min_y = min(p[1] for p in points)
            max_y = max(p[1] for p in points)
            result["namedview"] = {
                "content": annotation.properties.get("Text", ""),
                "min_x": min_x,
                "min_y": min_y,
                "max_x": max_x,
                "max_y": max_y,
                "width": max_x - min_x,
                "height": max_y - min_y,
            }
    elif anno_type == ANNOTATION_TYPE_HOTLINK:
        if len(tx_position) >= 2:
            hotlink = build_hotlink_from_annotation(annotation)
            if hotlink:
                result["hotlink"] = {
                    "uid": hotlink.uid,
                    "bid_page_uid": hotlink.bid_page_uid,
                    "center_x": tx_position[0],
                    "center_y": tx_position[1],
                    "target_view_uid": hotlink.target_view_uid,
                    "color": hotlink.color,
                    "width": hotlink.width,
                }
    return result


def _length(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _midpoint(a: Point, b: Point) -> Point:
    return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)


def _normalize(vx: float, vy: float) -> Point:
    L = math.hypot(vx, vy)
    if L == 0:
        return (0.0, 0.0)
    return (vx / L, vy / L)


def _ensure_clockwise(pts: List[Point]) -> List[Point]:
    if len(pts) < 3:
        return pts
    area = sum(
        pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
        for i in range(len(pts))
    )
    return pts[::-1] if area < 0 else pts


def _polygon_perimeter_edges(pts: List[Point]) -> List[Tuple[Point, Point, float]]:
    if len(pts) < 2:
        return []
    edges = []
    n = len(pts)
    for i in range(n):
        a = pts[i]
        b = pts[(i + 1) % n]
        L = _length(a, b)
        if L > 1e-9:
            edges.append((a, b, L))
    return edges


def _sample_along_perimeter(pts: List[Point], n_samples: int) -> List[Point]:
    edges = _polygon_perimeter_edges(pts)
    if not edges:
        return []
    perimeter = sum(e[2] for e in edges)
    samples = []
    for k in range(n_samples):
        t = (k * perimeter) / n_samples
        acc = 0.0
        for a, b, L in edges:
            if acc + L >= t:
                local = (t - acc) / L
                x = a[0] + (b[0] - a[0]) * local
                y = a[1] + (b[1] - a[1]) * local
                samples.append((x, y))
                break
            acc += L
    return samples


def _compute_centers_from_samples(
    samples: List[Point], radius: float, invert: bool
) -> List[Point]:
    n = len(samples)
    arr: List[Point] = [(0.0, 0.0)] * n
    for i in range(n):
        A = samples[i]
        B = samples[(i + 1) % n]
        mid = _midpoint(A, B)
        half_chord = _length(A, B) * 0.5
        inside = max(0.0, radius * radius - half_chord * half_chord)
        offset = math.sqrt(inside)
        dx = B[0] - A[0]
        dy = B[1] - A[1]
        tx, ty = _normalize(dx, dy)
        nx, ny = -ty, tx
        if invert:
            nx, ny = -nx, -ny
        cx = mid[0] + nx * offset
        cy = mid[1] + ny * offset
        arr[(i + 1) % n] = (cx, cy)
    return arr


def _arc_to_bezier(
    center: Point, radius: float, start_angle: float, end_angle: float
) -> List[Tuple[Point, Point, Point]]:
    kappa = 0.5522847498
    while end_angle < start_angle:
        end_angle += 2 * math.pi
    angle_span = end_angle - start_angle
    num_segments = max(1, int(math.ceil(abs(angle_span) / (math.pi / 2))))
    segment_angle = angle_span / num_segments
    segments = []
    cx, cy = center
    for i in range(num_segments):
        a1 = start_angle + i * segment_angle
        a2 = a1 + segment_angle
        cos_a1 = math.cos(a1)
        sin_a1 = math.sin(a1)
        cos_a2 = math.cos(a2)
        sin_a2 = math.sin(a2)
        x1 = cx + radius * cos_a1
        y1 = cy + radius * sin_a1
        x2 = cx + radius * cos_a2
        y2 = cy + radius * sin_a2
        if abs(segment_angle - math.pi / 2) > 1e-6:
            d = radius * kappa * math.tan(segment_angle / 4) / math.tan(math.pi / 8)
        else:
            d = radius * kappa
        cp1_x = x1 - d * sin_a1
        cp1_y = y1 + d * cos_a1
        cp2_x = x2 + d * sin_a2
        cp2_y = y2 - d * cos_a2
        segments.append(((cp1_x, cp1_y), (cp2_x, cp2_y), (x2, y2)))
    return segments
