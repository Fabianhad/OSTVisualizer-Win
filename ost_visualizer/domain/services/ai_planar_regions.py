import math
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
from .ai_linework import SegmentGrid, is_symbol_box

MAX_REGION_SEGMENTS = 20000
Point = Tuple[float, float]
Ring = Tuple[Point, ...]
Box = Tuple[float, float, float, float]


class RegionTooComplex(Exception):
    """Raised when a region search gets more segments than MAX_REGION_SEGMENTS."""


@dataclass(frozen=True)
class RegionGap:
    p1: Point
    p2: Point
    length: float


@dataclass(frozen=True)
class PlanarRegion:
    outer: Ring
    holes: Tuple[Ring, ...]
    area: float
    gaps: Tuple[RegionGap, ...]


@dataclass(frozen=True)
class PlanarRegionReport:
    regions: Tuple[PlanarRegion, ...]
    suppressed: Tuple[Box, ...]


def ring_area(ring: Sequence[Point]) -> float:
    total = 0.0
    count = len(ring)
    for index in range(count):
        x1, y1 = ring[index]
        x2, y2 = ring[(index + 1) % count]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def point_in_ring(point: Point, ring: Sequence[Point]) -> bool:
    x, y = point
    inside = False
    count = len(ring)
    for index in range(count):
        x1, y1 = ring[index]
        x2, y2 = ring[(index + 1) % count]
        if (y1 > y) != (y2 > y):
            crossing = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if crossing > x:
                inside = not inside
    return inside


class _VertexIndex:
    def __init__(self, tolerance: float):
        self._tolerance = tolerance
        self._cells: Dict[Tuple[int, int], List[int]] = defaultdict(list)
        self.points: List[Point] = []

    def _cell(self, point: Point) -> Tuple[int, int]:
        return (
            int(math.floor(point[0] / self._tolerance)),
            int(math.floor(point[1] / self._tolerance)),
        )

    def add(self, point: Point) -> int:
        cx, cy = self._cell(point)
        best = None
        best_distance = self._tolerance
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for vertex in self._cells.get((cx + dx, cy + dy), ()):
                    distance = math.dist(self.points[vertex], point)
                    if distance <= best_distance:
                        best = vertex
                        best_distance = distance
        if best is not None:
            return best
        self.points.append((float(point[0]), float(point[1])))
        vertex = len(self.points) - 1
        self._cells[(cx, cy)].append(vertex)
        return vertex


def _segment_point_parameter(a: Point, b: Point, p: Point) -> Tuple[float, float]:
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq == 0.0:
        return 0.0, math.dist(a, p)
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    foot = (a[0] + t * dx, a[1] + t * dy)
    return t, math.dist(foot, p)


def _intersection(
    a: Point, b: Point, c: Point, d: Point
) -> Optional[Tuple[float, Point]]:
    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = d[0] - c[0], d[1] - c[1]
    denominator = rx * sy - ry * sx
    if abs(denominator) < 1e-12:
        return None
    qx, qy = c[0] - a[0], c[1] - a[1]
    t = (qx * sy - qy * sx) / denominator
    u = (qx * ry - qy * rx) / denominator
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return t, (a[0] + t * rx, a[1] + t * ry)
    return None


def _candidate_pairs(segments: List[Tuple[Point, Point]], padding: float):
    if not segments:
        return []
    boxes = [
        (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        for a, b in segments
    ]
    grid = SegmentGrid(boxes)
    reach = 2.0 * padding
    pairs = []
    for first, (left, top, right, bottom) in enumerate(boxes):
        for second in grid.query(
            left - reach, top - reach, right + reach, bottom + reach
        ):
            if second <= first:
                continue
            other = boxes[second]
            if (
                other[0] - padding <= right + padding
                and left - padding <= other[2] + padding
                and other[1] - padding <= bottom + padding
                and top - padding <= other[3] + padding
            ):
                pairs.append((first, second))
    return pairs


def _split_segments(
    segments: List[Tuple[Point, Point]],
    index: _VertexIndex,
    tolerance: float,
    marked_from: Optional[int] = None,
) -> Tuple[Set[Tuple[int, int]], Set[Tuple[int, int]]]:
    splits: Dict[int, List[Tuple[float, Point]]] = defaultdict(list)
    for first, second in _candidate_pairs(segments, tolerance):
        a, b = segments[first]
        c, d = segments[second]
        hit = _intersection(a, b, c, d)
        if hit is not None:
            splits[first].append((hit[0], hit[1]))
            t_second, _distance = _segment_point_parameter(c, d, hit[1])
            splits[second].append((t_second, hit[1]))
        for owner, (p, q), others in (
            (first, (a, b), (c, d)),
            (second, (c, d), (a, b)),
        ):
            for endpoint in others:
                t, distance = _segment_point_parameter(p, q, endpoint)
                if distance <= tolerance:
                    foot = (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))
                    splits[owner].append((t, foot))
    for owner_splits in splits.values():
        for _t, point in owner_splits:
            index.add(point)
    edges: Set[Tuple[int, int]] = set()
    drawn: Set[Tuple[int, int]] = set()
    for position, (a, b) in enumerate(segments):
        points = [(0.0, a), (1.0, b)] + splits.get(position, [])
        points.sort(key=lambda item: item[0])
        vertices = []
        for _t, point in points:
            vertex = index.add(point)
            if not vertices or vertices[-1] != vertex:
                vertices.append(vertex)
        for u, v in zip(vertices, vertices[1:]):
            if u != v:
                edge = (min(u, v), max(u, v))
                edges.add(edge)
                if marked_from is None or position < marked_from:
                    drawn.add(edge)
    return edges, edges - drawn


def _adjacency(edges: Iterable[Tuple[int, int]]) -> Dict[int, Set[int]]:
    neighbours: Dict[int, Set[int]] = defaultdict(set)
    for u, v in edges:
        neighbours[u].add(v)
        neighbours[v].add(u)
    return neighbours


class _NearVertices:
    def __init__(self, points: List[Point], vertices: Iterable[int], reach: float):
        self._cell = reach * (1.0 + 1e-9) + 1e-12
        self._cells: Dict[Tuple[int, int], List[int]] = defaultdict(list)
        for vertex in vertices:
            self._cells[self._key(points[vertex])].append(vertex)

    def _key(self, point: Point) -> Tuple[int, int]:
        return (
            int(math.floor(point[0] / self._cell)),
            int(math.floor(point[1] / self._cell)),
        )

    def near(self, point: Point) -> List[int]:
        cx, cy = self._key(point)
        found = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                found.extend(self._cells.get((cx + dx, cy + dy), ()))
        return found


def _close_gaps(
    edges: Set[Tuple[int, int]], index: _VertexIndex, gap_close: float
) -> List[Tuple[int, int]]:
    if gap_close <= 0.0:
        return []
    closures = []
    neighbours = _adjacency(edges)
    dangling = sorted(vertex for vertex, near in neighbours.items() if len(near) == 1)
    order = {vertex: position for position, vertex in enumerate(neighbours)}
    near_dangling = _NearVertices(index.points, dangling, gap_close)
    near_any = _NearVertices(index.points, list(neighbours), gap_close)
    used: Set[int] = set()
    for vertex in dangling:
        if vertex in used:
            continue
        point = index.points[vertex]
        best = None
        best_distance = gap_close
        for other in sorted(near_dangling.near(point)):
            if (
                other == vertex
                or other in used
                or other in neighbours[vertex]
                or _runs_along_an_edge(index.points, neighbours, vertex, other)
            ):
                continue
            distance = math.dist(point, index.points[other])
            if distance <= best_distance:
                best = other
                best_distance = distance
        if best is None:
            for other in sorted(near_any.near(point), key=order.__getitem__):
                if (
                    other == vertex
                    or other in neighbours[vertex]
                    or len(neighbours[other]) < 2
                    or _runs_along_an_edge(index.points, neighbours, vertex, other)
                ):
                    continue
                distance = math.dist(point, index.points[other])
                if distance <= best_distance:
                    best = other
                    best_distance = distance
        if best is None:
            continue
        edge = (min(vertex, best), max(vertex, best))
        if edge in edges:
            continue
        edges.add(edge)
        neighbours[vertex].add(best)
        neighbours[best].add(vertex)
        closures.append(edge)
        used.add(vertex)
        used.add(best)
    return closures


def _runs_along_an_edge(
    points: List[Point], neighbours: Dict[int, Set[int]], first: int, second: int
) -> bool:
    for start, end in ((first, second), (second, first)):
        sx, sy = points[start]
        ex, ey = points[end][0] - sx, points[end][1] - sy
        for near in neighbours[start]:
            nx, ny = points[near][0] - sx, points[near][1] - sy
            length = math.hypot(ex, ey) * math.hypot(nx, ny)
            if abs(ex * ny - ey * nx) <= 1e-9 * length and ex * nx + ey * ny > 0.0:
                return True
    return False


def _prune_dangling(edges: Set[Tuple[int, int]]) -> None:
    neighbours = _adjacency(edges)
    queue = deque(vertex for vertex, near in neighbours.items() if len(near) == 1)
    while queue:
        vertex = queue.popleft()
        near = neighbours[vertex]
        if len(near) != 1:
            continue
        (other,) = near
        edges.discard((min(vertex, other), max(vertex, other)))
        near.clear()
        neighbours[other].discard(vertex)
        if len(neighbours[other]) == 1:
            queue.append(other)


def _trace_cycles(edges: Set[Tuple[int, int]], points: List[Point]) -> List[List[int]]:
    neighbours = _adjacency(edges)
    ordered = {
        vertex: sorted(
            near,
            key=lambda other, vertex=vertex: math.atan2(
                points[other][1] - points[vertex][1],
                points[other][0] - points[vertex][0],
            ),
        )
        for vertex, near in neighbours.items()
    }
    visited: Set[Tuple[int, int]] = set()
    cycles = []
    for u, v in sorted(edges):
        for start in ((u, v), (v, u)):
            if start in visited:
                continue
            cycle = []
            half = start
            while half not in visited:
                visited.add(half)
                cycle.append(half[0])
                tail, head = half
                around = ordered[head]
                position = around.index(tail)
                half = (head, around[position - 1])
            cycles.append(cycle)
    return cycles


def _components(edges: Set[Tuple[int, int]]) -> Dict[int, int]:
    parent: Dict[int, int] = {}

    def find(vertex: int) -> int:
        parent.setdefault(vertex, vertex)
        while parent[vertex] != vertex:
            parent[vertex] = parent[parent[vertex]]
            vertex = parent[vertex]
        return vertex

    for u, v in edges:
        parent[find(u)] = find(v)
    return {vertex: find(vertex) for vertex in list(parent)}


def _finite_pairs(segments) -> List[Tuple[Point, Point]]:
    return [
        ((float(x1), float(y1)), (float(x2), float(y2)))
        for x1, y1, x2, y2 in segments
        if all(math.isfinite(float(value)) for value in (x1, y1, x2, y2))
    ]


def find_planar_regions(
    segments: Sequence[Tuple[float, float, float, float]],
    snap_tol: float,
    gap_close: float,
    min_area: float = 1e-6,
) -> List[PlanarRegion]:
    return list(
        find_planar_regions_report(segments, snap_tol, gap_close, min_area).regions
    )


def find_planar_regions_report(
    segments: Sequence[Tuple[float, float, float, float]],
    snap_tol: float,
    gap_close: float,
    min_area: float = 1e-6,
    symbol_max: float = 0.0,
    closures: Sequence[Tuple[float, float, float, float]] = (),
) -> PlanarRegionReport:
    clean = _finite_pairs(segments)
    given = _finite_pairs(closures)
    if len(clean) + len(given) > MAX_REGION_SEGMENTS:
        raise RegionTooComplex(
            f"More than {MAX_REGION_SEGMENTS} line segments; use a smaller bounding box."
        )
    tolerance = max(float(snap_tol), 1e-6)
    index = _VertexIndex(tolerance)
    edges, given_edges = _split_segments(
        clean + given, index, tolerance, len(clean) if given else None
    )
    closures_found = _close_gaps(edges, index, float(gap_close))
    _prune_dangling(edges)
    points = index.points
    component_of = _components(edges)
    faces: Dict[int, List[List[int]]] = defaultdict(list)
    outers: Dict[int, List[int]] = {}
    for cycle in _trace_cycles(edges, points):
        ring = [points[vertex] for vertex in cycle]
        area = ring_area(ring)
        component = component_of[cycle[0]]
        if area > 0.0:
            faces[component].append(cycle)
        elif component not in outers or area < ring_area(
            [points[v] for v in outers[component]]
        ):
            outers[component] = cycle
    closure_set = set(closures_found) | given_edges
    candidates = []
    for component, component_faces in faces.items():
        for cycle in component_faces:
            candidates.append((component, cycle))
        if len(component_faces) > 1 and component in outers:
            candidates.append((component, list(reversed(outers[component]))))
    outer_rings = {
        component: tuple(points[vertex] for vertex in reversed(cycle))
        for component, cycle in outers.items()
    }
    ring_keys = list(outer_rings)
    ring_boxes = [_ring_box(outer_rings[key]) for key in ring_keys]
    box_grid = SegmentGrid(ring_boxes)
    suppressed: Dict[int, Box] = {}
    regions = []
    for component, cycle in candidates:
        ring = tuple(points[vertex] for vertex in cycle)
        holes = []
        inside = [
            ring_keys[position]
            for position in box_grid.query(*_ring_box(ring))
            if ring_keys[position] != component
            and _ring_inside(outer_rings[ring_keys[position]], ring)
        ]
        inside_set = set(inside)
        for other in inside:
            other_ring = outer_rings[other]
            other_box = _ring_box(other_ring)
            nested = any(
                ring_keys[position] not in (component, other)
                and ring_keys[position] in inside_set
                and _ring_inside(other_ring, outer_rings[ring_keys[position]])
                for position in box_grid.query(*other_box)
                if _box_contains(ring_boxes[position], other_box)
            )
            if nested:
                continue
            if is_symbol_box(other_box, symbol_max):
                suppressed[other] = other_box
                continue
            holes.append(other_ring)
        area = abs(ring_area(ring)) - sum(abs(ring_area(hole)) for hole in holes)
        if area <= min_area:
            continue
        ring_edges = {
            (min(u, v), max(u, v)) for u, v in zip(cycle, cycle[1:] + cycle[:1])
        }
        gaps = tuple(
            RegionGap(points[u], points[v], math.dist(points[u], points[v]))
            for u, v in sorted(closure_set & ring_edges)
        )
        regions.append(PlanarRegion(ring, tuple(holes), area, gaps))
    regions.sort(key=lambda region: -region.area)
    return PlanarRegionReport(
        tuple(regions), tuple(suppressed[key] for key in sorted(suppressed))
    )


def _ring_box(ring: Sequence[Point]) -> Box:
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    return (min(xs), min(ys), max(xs), max(ys))


def _box_contains(outer: Box, inner: Box) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[2] >= inner[2]
        and outer[3] >= inner[3]
    )


def _ring_inside(inner: Ring, outer: Ring) -> bool:
    if not inner:
        return False
    probe = inner[0]
    if any(math.dist(probe, vertex) < 1e-9 for vertex in outer):
        return False
    return point_in_ring(probe, outer) and abs(ring_area(inner)) < abs(ring_area(outer))
