import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

MAX_REGION_SEGMENTS = 4000
_GRID_CELLS = 64
Point = Tuple[float, float]
Ring = Tuple[Point, ...]


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
    xs = [value for a, b in segments for value in (a[0], b[0])]
    ys = [value for a, b in segments for value in (a[1], b[1])]
    width = max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)
    cell = width / _GRID_CELLS + padding
    origin = (min(xs), min(ys))
    buckets: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for index, (a, b) in enumerate(segments):
        x0 = int((min(a[0], b[0]) - padding - origin[0]) // cell)
        x1 = int((max(a[0], b[0]) + padding - origin[0]) // cell)
        y0 = int((min(a[1], b[1]) - padding - origin[1]) // cell)
        y1 = int((max(a[1], b[1]) + padding - origin[1]) // cell)
        for gx in range(x0, x1 + 1):
            for gy in range(y0, y1 + 1):
                buckets[(gx, gy)].append(index)
    pairs = set()
    for members in buckets.values():
        for i, first in enumerate(members):
            for second in members[i + 1 :]:
                pairs.add((first, second) if first < second else (second, first))
    return sorted(pairs)


def _split_segments(
    segments: List[Tuple[Point, Point]], index: _VertexIndex, tolerance: float
) -> Set[Tuple[int, int]]:
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
                edges.add((min(u, v), max(u, v)))
    return edges


def _adjacency(edges: Iterable[Tuple[int, int]]) -> Dict[int, Set[int]]:
    neighbours: Dict[int, Set[int]] = defaultdict(set)
    for u, v in edges:
        neighbours[u].add(v)
        neighbours[v].add(u)
    return neighbours


def _close_gaps(
    edges: Set[Tuple[int, int]], index: _VertexIndex, gap_close: float
) -> List[Tuple[int, int]]:
    if gap_close <= 0.0:
        return []
    closures = []
    neighbours = _adjacency(edges)
    dangling = sorted(vertex for vertex, near in neighbours.items() if len(near) == 1)
    used: Set[int] = set()
    for vertex in dangling:
        if vertex in used:
            continue
        point = index.points[vertex]
        best = None
        best_distance = gap_close
        for other in dangling:
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
            for other, near in neighbours.items():
                if (
                    other == vertex
                    or other in neighbours[vertex]
                    or len(near) < 2
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
    while True:
        neighbours = _adjacency(edges)
        removable = {
            (min(vertex, near_vertex), max(vertex, near_vertex))
            for vertex, near in neighbours.items()
            if len(near) == 1
            for near_vertex in near
        }
        if not removable:
            return
        edges.difference_update(removable)


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


def find_planar_regions(
    segments: Sequence[Tuple[float, float, float, float]],
    snap_tol: float,
    gap_close: float,
    min_area: float = 1e-6,
) -> List[PlanarRegion]:
    clean = [
        ((float(x1), float(y1)), (float(x2), float(y2)))
        for x1, y1, x2, y2 in segments
        if all(math.isfinite(float(value)) for value in (x1, y1, x2, y2))
    ]
    if len(clean) > MAX_REGION_SEGMENTS:
        raise RegionTooComplex(
            f"More than {MAX_REGION_SEGMENTS} line segments; use a smaller bounding box."
        )
    tolerance = max(float(snap_tol), 1e-6)
    index = _VertexIndex(tolerance)
    edges = _split_segments(clean, index, tolerance)
    closures = _close_gaps(edges, index, float(gap_close))
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
    closure_set = set(closures)
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
    regions = []
    for component, cycle in candidates:
        ring = tuple(points[vertex] for vertex in cycle)
        holes = []
        for other, other_ring in outer_rings.items():
            if other == component or not _ring_inside(other_ring, ring):
                continue
            nested = any(
                third not in (component, other)
                and _ring_inside(third_ring, ring)
                and _ring_inside(other_ring, third_ring)
                for third, third_ring in outer_rings.items()
            )
            if not nested:
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
    return regions


def _ring_inside(inner: Ring, outer: Ring) -> bool:
    if not inner:
        return False
    probe = inner[0]
    if any(math.dist(probe, vertex) < 1e-9 for vertex in outer):
        return False
    return point_in_ring(probe, outer) and abs(ring_area(inner)) < abs(ring_area(outer))
