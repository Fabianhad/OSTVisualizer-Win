import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
from .ai_linework import SegmentGrid, is_symbol_box

MAX_REGION_SEGMENTS = 20000
OPENING_ANGLE_DEG = 15.0
OPENING_NECK_RATIO = 3.0
PAIR_ANGLE_BUCKET_DEG = 1.0
PAIR_CELL_MIN_PADDINGS = 8.0
PAIR_MAX_CELLS_PER_SEGMENT = 4096
DEADLINE_CHECK_EVERY = 256
Point = Tuple[float, float]
Ring = Tuple[Point, ...]
Box = Tuple[float, float, float, float]


class RegionTooComplex(Exception):
    """Raised when a region search gets more segments than MAX_REGION_SEGMENTS."""


class RegionSearchTimeout(Exception):
    """The region search passed its deadline."""


@dataclass
class PairingWork:
    registered: int = 0
    examined: int = 0
    oversized: int = 0
    longest_walk: int = 0


def check_deadline(deadline: Optional[float]) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise RegionSearchTimeout("The region search ran out of time")


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

    def find(self, point: Point) -> Optional[int]:
        cx, cy = self._cell(point)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for vertex in self._cells.get((cx + dx, cy + dy), ()):
                    if math.dist(self.points[vertex], point) <= self._tolerance:
                        return vertex
        return None


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


def _pair_cell_size(segments: List[Tuple[Point, Point]], padding: float) -> float:
    xs = [value for a, b in segments for value in (a[0], b[0])]
    ys = [value for a, b in segments for value in (a[1], b[1])]
    extent = max(max(xs) - min(xs), max(ys) - min(ys))
    lengths = sorted(math.dist(a, b) for a, b in segments)
    typical = lengths[len(lengths) // 2]
    return max(
        min(typical, extent / max(1.0, math.sqrt(len(segments)))),
        PAIR_CELL_MIN_PADDINGS * padding,
        1e-6,
    )


def _near_cells(a: Point, b: Point, reach: float, cell: float):
    (x1, y1), (x2, y2) = (a, b) if a[0] <= b[0] else (b, a)
    dx = x2 - x1
    dy = y2 - y1
    for column in range(
        int(math.floor((x1 - reach) / cell)), int(math.floor((x2 + reach) / cell)) + 1
    ):
        if dx == 0.0:
            low, high = min(y1, y2), max(y1, y2)
        else:
            left = max(x1, column * cell - reach)
            right = min(x2, (column + 1) * cell + reach)
            if left > right:
                continue
            ya = y1 + (left - x1) / dx * dy
            yb = y1 + (right - x1) / dx * dy
            low, high = min(ya, yb), max(ya, yb)
        for row in range(
            int(math.floor((low - reach) / cell)),
            int(math.floor((high + reach) / cell)) + 1,
        ):
            yield column, row


def _walk_estimate(a: Point, b: Point, reach: float, cell: float) -> int:
    columns = (
        int(math.floor((max(a[0], b[0]) + reach) / cell))
        - int(math.floor((min(a[0], b[0]) - reach) / cell))
        + 1
    )
    rows = (
        int(math.floor((max(a[1], b[1]) + reach) / cell))
        - int(math.floor((min(a[1], b[1]) - reach) / cell))
        + 1
    )
    return rows + 3 * columns


def _direction_bucket(a: Point, b: Point, buckets: int) -> Optional[int]:
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    if dx == 0.0 and dy == 0.0:
        return None
    step = math.pi / buckets
    angle = math.atan2(dy, dx) % math.pi
    return int(math.floor((angle + step / 2.0) / step)) % buckets


def _line_offset(a: Point, b: Point, normal: Point, center: Point) -> float:
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    t = ((center[0] - a[0]) * dx + (center[1] - a[1]) * dy) / (dx * dx + dy * dy)
    return normal[0] * (a[0] + t * dx) + normal[1] * (a[1] + t * dy)


def _add_pair(
    first: int, second: int, boxes: List[Box], found: Set[Tuple[int, int]]
) -> None:
    a = boxes[first]
    b = boxes[second]
    if a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]:
        found.add((first, second) if first < second else (second, first))


def _cell_pairs(
    members: List[int],
    segments: List[Tuple[Point, Point]],
    buckets: List[Optional[int]],
    boxes: List[Box],
    center: Point,
    window: float,
    found: Set[Tuple[int, int]],
) -> int:
    examined = 0
    groups: Dict[Optional[int], List[int]] = defaultdict(list)
    for member in members:
        groups[buckets[member]].append(member)
    keys = sorted(groups, key=lambda key: -1 if key is None else key)
    for position, key in enumerate(keys):
        group = groups[key]
        for other_key in keys[position + 1 :]:
            examined += len(group) * len(groups[other_key])
            for first in group:
                for second in groups[other_key]:
                    _add_pair(first, second, boxes, found)
        if key is None:
            examined += len(group) * (len(group) - 1) // 2
            for index, first in enumerate(group):
                for second in group[index + 1 :]:
                    _add_pair(first, second, boxes, found)
            continue
        angle = key * math.radians(PAIR_ANGLE_BUCKET_DEG)
        normal = (-math.sin(angle), math.cos(angle))
        ordered = sorted(
            (_line_offset(*segments[member], normal, center), member)
            for member in group
        )
        for index, (offset, first) in enumerate(ordered):
            for other_offset, second in ordered[index + 1 :]:
                if other_offset - offset > window:
                    break
                examined += 1
                _add_pair(first, second, boxes, found)
    return examined


def _candidate_pairs(
    segments: List[Tuple[Point, Point]],
    padding: float,
    deadline: Optional[float] = None,
) -> List[Tuple[int, int]]:
    return _candidate_pairs_with_work(segments, padding, deadline)[0]


def _candidate_pairs_with_work(
    segments: List[Tuple[Point, Point]],
    padding: float,
    deadline: Optional[float] = None,
) -> Tuple[List[Tuple[int, int]], PairingWork]:
    work = PairingWork()
    if not segments:
        return [], work
    cell = _pair_cell_size(segments, padding)
    reach = padding * (1.0 + 1e-9) + 1e-9
    count = int(round(180.0 / PAIR_ANGLE_BUCKET_DEG))
    buckets = [_direction_bucket(a, b, count) for a, b in segments]
    boxes = [
        (
            min(a[0], b[0]) - padding,
            min(a[1], b[1]) - padding,
            max(a[0], b[0]) + padding,
            max(a[1], b[1]) + padding,
        )
        for a, b in segments
    ]
    cells: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    oversized: List[int] = []
    for position, (a, b) in enumerate(segments):
        check_deadline(deadline)
        if _walk_estimate(a, b, reach, cell) > PAIR_MAX_CELLS_PER_SEGMENT:
            oversized.append(position)
            continue
        walked = 0
        for key in _near_cells(a, b, reach, cell):
            cells[key].append(position)
            walked += 1
        work.registered += walked
        work.longest_walk = max(work.longest_walk, walked)
    work.oversized = len(oversized)
    half_angle = math.radians(PAIR_ANGLE_BUCKET_DEG) / 2.0
    window = (
        reach + (2.0 * math.sqrt(2.0) * cell + 2.0 * reach) * math.sin(half_angle)
    ) * (1.0 + 1e-9) + 1e-9
    found: Set[Tuple[int, int]] = set()
    for visited, ((column, row), members) in enumerate(cells.items()):
        if visited % DEADLINE_CHECK_EVERY == 0:
            check_deadline(deadline)
        if len(members) < 2:
            continue
        center = ((column + 0.5) * cell, (row + 0.5) * cell)
        work.examined += _cell_pairs(
            members, segments, buckets, boxes, center, window, found
        )
    for first in oversized:
        for second in range(len(segments)):
            if second % DEADLINE_CHECK_EVERY == 0:
                check_deadline(deadline)
            if second != first:
                _add_pair(first, second, boxes, found)
        work.examined += len(segments) - 1
    return sorted(found), work


def _split_segments(
    segments: List[Tuple[Point, Point]],
    index: _VertexIndex,
    tolerance: float,
    marked_from: Optional[int] = None,
    deadline: Optional[float] = None,
) -> Tuple[Set[Tuple[int, int]], Set[Tuple[int, int]]]:
    splits: Dict[int, List[Tuple[float, Point]]] = defaultdict(list)
    for checked, (first, second) in enumerate(
        _candidate_pairs(segments, tolerance, deadline)
    ):
        if checked % DEADLINE_CHECK_EVERY == 0:
            check_deadline(deadline)
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
        if position % DEADLINE_CHECK_EVERY == 0:
            check_deadline(deadline)
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


def _trace_cycles(
    edges: Set[Tuple[int, int]],
    points: List[Point],
    deadline: Optional[float] = None,
) -> List[List[int]]:
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
    for checked, (u, v) in enumerate(sorted(edges)):
        if checked % DEADLINE_CHECK_EVERY == 0:
            check_deadline(deadline)
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


def check_segment_count(count: int) -> None:
    if count > MAX_REGION_SEGMENTS:
        raise RegionTooComplex(
            f"More than {MAX_REGION_SEGMENTS} line segments; use a smaller bounding box."
        )


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
    deadline: Optional[float] = None,
) -> PlanarRegionReport:
    clean = _finite_pairs(segments)
    given = _finite_pairs(closures)
    check_segment_count(len(clean) + len(given))
    tolerance = max(float(snap_tol), 1e-6)
    index = _VertexIndex(tolerance)
    edges, given_edges = _split_segments(
        clean + given, index, tolerance, len(clean) if given else None, deadline
    )
    closures_found = _close_gaps(edges, index, float(gap_close))
    _prune_dangling(edges)
    points = index.points
    component_of = _components(edges)
    faces: Dict[int, List[List[int]]] = defaultdict(list)
    outers: Dict[int, List[int]] = {}
    for cycle in _trace_cycles(edges, points, deadline):
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
        check_deadline(deadline)
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
            check_deadline(deadline)
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


def opening_candidates(
    segments: Sequence[Tuple[float, float, float, float]],
    snap_tol: float,
    min_length: float,
    max_length: float,
    ring: Sequence[Point] = (),
) -> List[Tuple[float, float, float, float]]:
    clean = _finite_pairs(segments)
    tolerance = max(float(snap_tol), 1e-6)
    index = _VertexIndex(tolerance)
    edges, _given = _split_segments(clean, index, tolerance)
    points = index.points
    neighbours = _adjacency(edges)
    edge_list = sorted(edges)
    grid = SegmentGrid([points[u] + points[v] for u, v in edge_list])
    cosine = math.cos(math.radians(OPENING_ANGLE_DEG))
    found: Dict[Tuple[int, int], Tuple[Point, Point]] = {}
    unbounded = (-math.inf, -math.inf, math.inf, math.inf)
    left, top, right, bottom = _ring_box(ring) if ring else unbounded
    chain_ends = {
        vertex: _chain_end(neighbours, vertex)
        for vertex, near in neighbours.items()
        if len(near) == 1
    }
    outward = {
        vertex: _unit(points[next(iter(neighbours[vertex]))], points[vertex])
        for vertex in chain_ends
    }
    attached = _NearVertices(
        points,
        [vertex for vertex, end in chain_ends.items() if end is None],
        max_length,
    )

    def facing(vertex: int, other: int) -> bool:
        distance = math.dist(points[vertex], points[other])
        chord = (
            points[other][0] - points[vertex][0],
            points[other][1] - points[vertex][1],
        )
        return (
            min_length < distance <= max_length
            and _dot(outward[vertex], chord) >= cosine * distance
            and -_dot(outward[other], chord) >= cosine * distance
        )

    for vertex in sorted(chain_ends):
        point = points[vertex]
        if not (
            left - tolerance <= point[0] <= right + tolerance
            and top - tolerance <= point[1] <= bottom + tolerance
        ):
            continue
        end = chain_ends[vertex]
        best = min(
            (
                (math.dist(point, points[other]), points[other])
                for other in ([end] if end is not None else attached.near(point))
                if facing(vertex, other)
            ),
            default=None,
        )
        if best is None and end is None:
            best = _facing_foot(
                point, outward[vertex], grid, min_length, max_length, cosine
            )
        if best is not None:
            _keep_opening(found, point, best[1], grid, tolerance)
    jambs = [index.find(point) for point in ring]
    along = [0.0]
    for position, point in enumerate(ring):
        along.append(along[-1] + math.dist(point, ring[(position + 1) % len(ring)]))

    def jamb_pair(position: int, other_position: int) -> bool:
        vertex = jambs[position]
        other = jambs[other_position]
        distance = math.dist(points[vertex], points[other])
        path = abs(along[other_position] - along[position])
        if (
            not min_length < distance <= max_length
            or min(path, along[-1] - path) < OPENING_NECK_RATIO * distance
        ):
            return False
        chord = _unit(points[vertex], points[other])
        middle = (
            (points[vertex][0] + points[other][0]) / 2.0,
            (points[vertex][1] + points[other][1]) / 2.0,
        )
        return (
            _continues(points, neighbours, vertex, chord, cosine)
            and _continues(points, neighbours, other, (-chord[0], -chord[1]), cosine)
            and grid.distance(middle, tolerance) > tolerance
            and point_in_ring(middle, ring)
        )

    corners = [position for position, vertex in enumerate(jambs) if vertex is not None]
    near_corners = _NearVertices(list(ring), corners, max_length)
    for position in corners:
        start = points[jambs[position]]
        best = min(
            (
                (math.dist(start, points[jambs[other]]), points[jambs[other]])
                for other in near_corners.near(ring[position])
                if jamb_pair(position, other)
            ),
            default=None,
        )
        if best is not None:
            _keep_opening(found, start, best[1], grid, tolerance)
    return [first + second for first, second in found.values()]


def _unit(start: Point, end: Point) -> Point:
    length = math.dist(start, end)
    return ((end[0] - start[0]) / length, (end[1] - start[1]) / length)


def _dot(first: Point, second: Point) -> float:
    return first[0] * second[0] + first[1] * second[1]


def _chain_end(neighbours: Dict[int, Set[int]], vertex: int) -> Optional[int]:
    previous, current = vertex, next(iter(neighbours[vertex]))
    while len(neighbours[current]) == 2:
        previous, current = current, next(
            other for other in neighbours[current] if other != previous
        )
    return current if len(neighbours[current]) == 1 else None


def _continues(
    points: List[Point],
    neighbours: Dict[int, Set[int]],
    vertex: int,
    chord: Point,
    cosine: float,
) -> bool:
    return any(
        _dot(_unit(points[near], points[vertex]), chord) >= cosine
        for near in neighbours[vertex]
    )


def _facing_foot(
    point: Point,
    outward: Point,
    grid: SegmentGrid,
    min_length: float,
    max_length: float,
    cosine: float,
) -> Optional[Tuple[float, Point]]:
    x, y = point
    feet = []
    for position in grid.query(
        x - max_length, y - max_length, x + max_length, y + max_length
    ):
        x1, y1, x2, y2 = grid.segment(position)
        t, distance = _segment_point_parameter((x1, y1), (x2, y2), point)
        foot = (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
        if (
            min_length < distance <= max_length
            and _dot(outward, (foot[0] - x, foot[1] - y)) >= cosine * distance
        ):
            feet.append((distance, foot))
    return min(feet, default=None)


def _keep_opening(
    found: Dict[Tuple[int, int], Tuple[Point, Point]],
    first: Point,
    second: Point,
    grid: SegmentGrid,
    tolerance: float,
) -> None:
    length = math.dist(first, second)
    margin = tolerance / length
    for position in grid.query(
        min(first[0], second[0]),
        min(first[1], second[1]),
        max(first[0], second[0]),
        max(first[1], second[1]),
    ):
        x1, y1, x2, y2 = grid.segment(position)
        hit = _intersection(first, second, (x1, y1), (x2, y2))
        if hit is not None and margin < hit[0] < 1.0 - margin:
            return
    key = tuple(sorted((_grid_key(first, tolerance), _grid_key(second, tolerance))))
    found.setdefault(key, (first, second))


def _grid_key(point: Point, tolerance: float) -> Tuple[int, int]:
    return (int(round(point[0] / tolerance)), int(round(point[1] / tolerance)))


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
