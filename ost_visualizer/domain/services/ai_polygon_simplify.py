import math
from dataclasses import dataclass
from typing import List, Sequence, Tuple
from ..entities.ai_changeset import polygon_area, ring_within
from .ai_linework import SegmentGrid
from .ai_planar_regions import point_in_ring

SIMPLIFY_TOLERANCE_IN = 0.25
AREA_TOLERANCE = 0.001
MIN_TOLERANCE_IN = 1e-4
Flat = Tuple[float, ...]
Point = Tuple[float, float]


@dataclass(frozen=True)
class SimplifiedSlab:
    outline: Flat
    holes: Tuple[Flat, ...]
    holes_dropped: int
    outline_vertices: Tuple[int, int]
    hole_vertices: Tuple[int, int]
    area_change_pct: float


def _points(ring: Flat) -> List[Point]:
    return [(float(ring[i]), float(ring[i + 1])) for i in range(0, len(ring) - 1, 2)]


def _distance(point: Point, start: Point, end: Point) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    return abs(dx * (start[1] - point[1]) - dy * (start[0] - point[0])) / math.hypot(
        dx, dy
    )


def _douglas_peucker(points: List[Point], tolerance: float) -> List[Point]:
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        worst, index = -1.0, -1
        for position in range(first + 1, last):
            distance = _distance(points[position], points[first], points[last])
            if distance > worst:
                worst, index = distance, position
        if worst > tolerance:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return [point for point, flag in zip(points, keep) if flag]


def _simplified_once(points: List[Point], tolerance: float) -> List[Point]:
    far = max(range(len(points)), key=lambda index: math.dist(points[0], points[index]))
    first = _douglas_peucker(points[: far + 1], tolerance)
    second = _douglas_peucker(points[far:] + points[:1], tolerance)
    return first[:-1] + second[:-1]


def simplify_ring(ring: Flat, tolerance: float = SIMPLIFY_TOLERANCE_IN) -> Flat:
    points = _points(ring)
    area = abs(polygon_area(tuple(ring)))
    if len(points) <= 3 or area == 0.0:
        return tuple(ring)
    while tolerance >= MIN_TOLERANCE_IN:
        simplified = _simplified_once(points, tolerance)
        if len(simplified) >= 3:
            flat = tuple(value for point in simplified for value in point)
            if abs(abs(polygon_area(flat)) - area) <= AREA_TOLERANCE * area:
                return flat
        tolerance /= 2.0
    return tuple(ring)


def _net_area(outline: Flat, holes: Sequence[Flat]) -> float:
    return abs(polygon_area(outline)) - sum(abs(polygon_area(hole)) for hole in holes)


def _orientation(p: Point, q: Point, r: Point) -> int:
    value = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return 0 if value == 0.0 else (1 if value > 0.0 else -1)


def _on_segment(p: Point, q: Point, r: Point) -> bool:
    return min(p[0], q[0]) <= r[0] <= max(p[0], q[0]) and min(p[1], q[1]) <= r[
        1
    ] <= max(p[1], q[1])


def _touch(a: Point, b: Point, c: Point, d: Point) -> bool:
    o1, o2 = _orientation(a, b, c), _orientation(a, b, d)
    o3, o4 = _orientation(c, d, a), _orientation(c, d, b)
    if o1 != o2 and o3 != o4:
        return True
    return (
        (o1 == 0 and _on_segment(a, b, c))
        or (o2 == 0 and _on_segment(a, b, d))
        or (o3 == 0 and _on_segment(c, d, a))
        or (o4 == 0 and _on_segment(c, d, b))
    )


def has_contacts(rings: Sequence[Flat]) -> bool:
    edges = []
    for ring_index, ring in enumerate(rings):
        points = _points(ring)
        for index, start in enumerate(points):
            edges.append(
                (
                    ring_index,
                    index,
                    len(points),
                    start,
                    points[(index + 1) % len(points)],
                )
            )
    grid = SegmentGrid([(a[0], a[1], b[0], b[1]) for _r, _i, _n, a, b in edges])
    for position, (ring, index, count, a, b) in enumerate(edges):
        for other in grid.query(
            min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])
        ):
            if other <= position:
                continue
            other_ring, other_index, _count, c, d = edges[other]
            if other_ring == ring and (other_index - index) % count in (1, count - 1):
                continue
            if _touch(a, b, c, d):
                return True
    return False


def _area_holds(before: float, after: float) -> bool:
    return abs(after - before) <= AREA_TOLERANCE * abs(before)


def _simplified_rings(rings: List[Flat], tolerance: float) -> List[Flat]:
    while tolerance >= MIN_TOLERANCE_IN:
        candidate = []
        for ring in rings:
            points = _points(ring)
            simplified = (
                _simplified_once(points, tolerance) if len(points) > 3 else points
            )
            candidate.append(tuple(value for point in simplified for value in point))
        if (
            all(
                _area_holds(abs(polygon_area(old)), abs(polygon_area(new)))
                for old, new in zip(rings, candidate)
            )
            and _area_holds(
                _net_area(rings[0], rings[1:]), _net_area(candidate[0], candidate[1:])
            )
            and all(ring_within(hole, candidate[0]) for hole in candidate[1:])
            and not has_contacts(candidate)
        ):
            return candidate
        tolerance /= 2.0
    return rings


def _fits(hole: Flat, outline: Flat) -> bool:
    if not has_contacts([outline, hole]):
        return point_in_ring(_points(hole)[0], _points(outline))
    return ring_within(hole, outline)


def simplify_slab(
    outline: Flat, holes: Sequence[Flat], tolerance: float = SIMPLIFY_TOLERANCE_IN
) -> SimplifiedSlab:
    outline = tuple(outline)
    kept = [tuple(hole) for hole in holes if _fits(tuple(hole), outline)]
    original = [outline, *kept]
    if abs(polygon_area(outline)) == 0.0:
        simplified = original
    else:
        simplified = _simplified_rings(original, tolerance)
    before = _net_area(outline, kept)
    after = _net_area(simplified[0], simplified[1:])
    change = 0.0 if before == 0.0 else (after - before) / before * 100.0
    return SimplifiedSlab(
        simplified[0],
        tuple(simplified[1:]),
        len(holes) - len(kept),
        (len(outline) // 2, len(simplified[0]) // 2),
        (
            sum(len(hole) // 2 for hole in kept),
            sum(len(hole) // 2 for hole in simplified[1:]),
        ),
        change,
    )
