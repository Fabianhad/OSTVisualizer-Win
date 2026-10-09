import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Sequence, Set, Tuple
from .ai_linework import (
    DASH_GAP_MAX_PTS,
    DASH_GAP_MIN_PTS,
    DASH_MIN_PIECES,
    DASH_NEIGHBOUR_LIMIT,
    DASH_OFFSET_TOLERANCE_PTS,
    DASH_PIECE_MAX_PTS,
    KIND_DASHED,
    KIND_SYMBOL,
    LineSegment,
    SegmentGrid,
    collinear_gap,
    point_segment_distance,
)

DASH_BRIDGE_TOLERANCE_PTS = 0.5
DASH_BRIDGE_TOLERANCE_SHARE = 0.1
DASH_BRIDGE_ANGLE_DEG = 30.0
DASH_CORNER_MAX_PTS = 2.0 * DASH_PIECE_MAX_PTS
DASH_JOIN_PTS = 0.5
RUN_CELL_PTS = 2.0
STYLE_WIDTH_DECIMALS = 2
Segment = Tuple[float, float, float, float]
Point = Tuple[float, float]
StyleKey = Tuple[float, str, bool]


@dataclass(frozen=True)
class DashedBoundary:
    pieces: Dict[int, float]
    bridges: Tuple[Segment, ...]


def dash_pattern_gap(dash: Sequence[float]) -> float:
    values = [float(value) for value in dash]
    if len(values) % 2:
        values = values * 2
    return min(max(values[1::2], default=0.0), DASH_GAP_MAX_PTS)


def bridge_limit(gap: float) -> float:
    return gap + max(DASH_BRIDGE_TOLERANCE_PTS, DASH_BRIDGE_TOLERANCE_SHARE * gap)


def style_key(line: LineSegment) -> StyleKey:
    return (
        round(float(line.width or 0.0), STYLE_WIDTH_DECIMALS),
        line.color,
        line.stroked,
    )


def dashed_boundary(
    lines: Sequence[LineSegment], kinds: Sequence[str]
) -> DashedBoundary:
    pieces = dashed_pieces(lines, kinds)
    return DashedBoundary(pieces, tuple(dash_bridges(lines, pieces)))


def dashed_pieces(
    lines: Sequence[LineSegment], kinds: Sequence[str]
) -> Dict[int, float]:
    pieces: Dict[int, float] = {}
    for index, line in enumerate(lines):
        if line.has_dash and kinds[index] != KIND_SYMBOL:
            pieces[index] = dash_pattern_gap(line.dash)
    groups: Dict[StyleKey, List[int]] = defaultdict(list)
    for index, line in enumerate(lines):
        if (
            index not in pieces
            and line.stroked
            and not line.closed
            and kinds[index] != KIND_SYMBOL
            and line.length > 0.0
        ):
            groups[style_key(line)].append(index)
    for members in groups.values():
        pieces.update(_exploded_runs(lines, members))
    pieces.update(_classified_gaps(lines, kinds, pieces))
    for members in groups.values():
        pieces.update(_corner_chains(lines, members, pieces))
    return pieces


class _BoxHash:
    def __init__(self, boxes: List[Tuple[float, float, float, float]], cell: float):
        self._cell = cell
        self._cells: Dict[Tuple[int, int], List[int]] = defaultdict(list)
        for position, box in enumerate(boxes):
            for key in self._keys(box):
                self._cells[key].append(position)

    def _keys(self, box: Tuple[float, float, float, float]):
        left, top, right, bottom = (
            int(math.floor(value / self._cell)) for value in box
        )
        return (
            (column, row)
            for column in range(left, right + 1)
            for row in range(top, bottom + 1)
        )

    def query(self, box: Tuple[float, float, float, float]) -> Set[int]:
        return {
            position for key in self._keys(box) for position in self._cells.get(key, ())
        }


class _EndHash:
    def __init__(self, lines: List[LineSegment]):
        self._cells: Dict[Tuple[int, int], List[int]] = defaultdict(list)
        for position, line in enumerate(lines):
            for point in set(_ends(line)):
                self._cells[self._key(point)].append(position)

    @staticmethod
    def _key(point: Point) -> Tuple[int, int]:
        return (
            int(math.floor(point[0] / DASH_JOIN_PTS)),
            int(math.floor(point[1] / DASH_JOIN_PTS)),
        )

    def near(self, line: LineSegment) -> Set[int]:
        found: Set[int] = set()
        for point in _ends(line):
            column, row = self._key(point)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    found.update(self._cells.get((column + dx, row + dy), ()))
        return found


def _meets(segment: Segment, box: Tuple[float, float, float, float]) -> bool:
    x1, y1, x2, y2 = segment
    return (
        min(x1, x2) <= box[2]
        and max(x1, x2) >= box[0]
        and min(y1, y2) <= box[3]
        and max(y1, y2) >= box[1]
    )


def _box(segment: Segment, padding: float) -> Tuple[float, float, float, float]:
    x1, y1, x2, y2 = segment
    return (
        min(x1, x2) - padding,
        min(y1, y2) - padding,
        max(x1, x2) + padding,
        max(y1, y2) + padding,
    )


class _Union:
    def __init__(self, size: int):
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def join(self, first: int, second: int) -> None:
        self.parent[self.find(second)] = self.find(first)

    def groups(self) -> List[List[int]]:
        found: Dict[int, List[int]] = defaultdict(list)
        for item in range(len(self.parent)):
            found[self.find(item)].append(item)
        return list(found.values())


def _axis(segment: LineSegment) -> Tuple[float, float, float, float]:
    length = segment.length
    return (
        segment.x1,
        segment.y1,
        (segment.x2 - segment.x1) / length,
        (segment.y2 - segment.y1) / length,
    )


def _extent(segment: LineSegment, axis) -> Tuple[float, float]:
    ox, oy, ux, uy = axis
    start = (segment.x1 - ox) * ux + (segment.y1 - oy) * uy
    end = (segment.x2 - ox) * ux + (segment.y2 - oy) * uy
    return min(start, end), max(start, end)


def _run(lines: Sequence[LineSegment], members: List[int]) -> LineSegment:
    axis = _axis(lines[members[0]])
    spans = [_extent(lines[index], axis) for index in members]
    low = min(span[0] for span in spans)
    high = max(span[1] for span in spans)
    ox, oy, ux, uy = axis
    return LineSegment(ox + ux * low, oy + uy * low, ox + ux * high, oy + uy * high)


def _exploded_runs(
    lines: Sequence[LineSegment], members: List[int]
) -> Dict[int, float]:
    short = [index for index in members if lines[index].length <= DASH_PIECE_MAX_PTS]
    joined = _Union(len(short))
    reach = DASH_GAP_MIN_PTS + DASH_OFFSET_TOLERANCE_PTS
    grid = _BoxHash([_box(lines[index].points, 0.0) for index in short], RUN_CELL_PTS)
    for position, index in enumerate(short):
        area = _box(lines[index].points, reach)
        for other in grid.query(area):
            if other > position and _meets(lines[short[other]].points, area):
                gap = collinear_gap(lines[index], lines[short[other]])
                if gap is not None and gap < DASH_GAP_MIN_PTS:
                    joined.join(position, other)
    runs = []
    for group in joined.groups():
        indices = [short[position] for position in group]
        run = _run(lines, indices)
        if run.length <= DASH_PIECE_MAX_PTS:
            runs.append((run, indices))
    if len(runs) < DASH_MIN_PIECES:
        return {}
    size = DASH_GAP_MAX_PTS + DASH_OFFSET_TOLERANCE_PTS
    cells = [_cell(run, size) for run, _indices in runs]
    counts: Dict[Tuple[int, int], int] = defaultdict(int)
    for cell in cells:
        counts[cell] += 1
    crowded = {
        position
        for position, (column, row) in enumerate(cells)
        if sum(
            counts.get((column + dx, row + dy), 0)
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
        )
        > DASH_NEIGHBOUR_LIMIT
    }
    clusters = _Union(len(runs))
    run_grid = SegmentGrid([run.points for run, _indices in runs])
    for position, (run, _indices) in enumerate(runs):
        if position in crowded:
            continue
        area = _box(run.points, size)
        for other in run_grid.query(*area):
            if (
                other <= position
                or other in crowded
                or not _meets(runs[other][0].points, area)
            ):
                continue
            gap = collinear_gap(run, runs[other][0])
            if gap is not None and DASH_GAP_MIN_PTS <= gap <= DASH_GAP_MAX_PTS + 1e-9:
                clusters.join(position, other)
    found: Dict[int, float] = {}
    for group in clusters.groups():
        if len(group) < DASH_MIN_PIECES:
            continue
        gap = _pattern_gap([runs[position][0] for position in group])
        for position in group:
            for index in runs[position][1]:
                found[index] = gap
    return found


def _cell(run: LineSegment, size: float) -> Tuple[int, int]:
    return (
        int(math.floor((run.x1 + run.x2) / 2.0 / size)),
        int(math.floor((run.y1 + run.y2) / 2.0 / size)),
    )


def _pattern_gap(runs: List[LineSegment]) -> float:
    axis = _axis(runs[0])
    spans = sorted(_extent(run, axis) for run in runs)
    gaps = [
        following[0] - current[1]
        for current, following in zip(spans, spans[1:])
        if DASH_GAP_MIN_PTS <= following[0] - current[1] <= DASH_GAP_MAX_PTS + 1e-9
    ]
    return statistics.median(gaps) if gaps else 0.0


def _classified_gaps(
    lines: Sequence[LineSegment], kinds: Sequence[str], pieces: Dict[int, float]
) -> Dict[int, float]:
    classified = [
        index
        for index, kind in enumerate(kinds)
        if kind == KIND_DASHED and lines[index].length > 0.0
    ]
    grid = SegmentGrid([lines[index].points for index in classified])
    found: Dict[int, float] = {}
    for index in classified:
        if index in pieces:
            continue
        best = math.inf
        area = _box(lines[index].points, DASH_GAP_MAX_PTS + DASH_OFFSET_TOLERANCE_PTS)
        for other in grid.query(*area):
            if not _meets(lines[classified[other]].points, area):
                continue
            gap = collinear_gap(lines[index], lines[classified[other]])
            if gap is not None and DASH_GAP_MIN_PTS <= gap < best:
                best = gap
        found[index] = best if best <= DASH_GAP_MAX_PTS else 0.0
    return found


def _ends(line: LineSegment) -> Tuple[Point, Point]:
    return (line.x1, line.y1), (line.x2, line.y2)


def _touches(first: LineSegment, second: LineSegment) -> bool:
    return any(
        math.dist(a, b) <= DASH_JOIN_PTS for a in _ends(first) for b in _ends(second)
    )


def _corner_chains(
    lines: Sequence[LineSegment], members: List[int], pieces: Dict[int, float]
) -> Dict[int, float]:
    dashed = [index for index in members if index in pieces]
    loose = [
        index
        for index in members
        if index not in pieces and lines[index].length <= DASH_PIECE_MAX_PTS
    ]
    if not dashed or not loose:
        return {}
    chains = _Union(len(loose))
    loose_ends = _EndHash([lines[index] for index in loose])
    for position, index in enumerate(loose):
        for other in loose_ends.near(lines[index]):
            if other > position and _touches(lines[index], lines[loose[other]]):
                chains.join(position, other)
    dashed_ends = _EndHash([lines[index] for index in dashed])
    found: Dict[int, float] = {}
    for group in chains.groups():
        indices = [loose[position] for position in group]
        if sum(lines[index].length for index in indices) > DASH_CORNER_MAX_PTS:
            continue
        touched = {
            dashed[other]
            for index in indices
            for other in dashed_ends.near(lines[index])
            if _touches(lines[index], lines[dashed[other]])
        }
        if touched:
            gap = max(pieces[index] for index in touched)
            for index in indices:
                found[index] = gap
    return found


@dataclass(frozen=True)
class _End:
    point: Point
    outward: Point
    limit: float
    style: StyleKey


def dash_bridges(
    lines: Sequence[LineSegment], pieces: Dict[int, float]
) -> List[Segment]:
    indices = sorted(index for index in pieces if lines[index].length > 0.0)
    grid = SegmentGrid([lines[index].points for index in indices])
    ends: List[_End] = []
    cosine = math.cos(math.radians(DASH_BRIDGE_ANGLE_DEG))
    for index in indices:
        line = lines[index]
        start, end = _ends(line)
        for point, other in ((start, end), (end, start)):
            outward = (
                (point[0] - other[0]) / line.length,
                (point[1] - other[1]) / line.length,
            )
            if _continued(point, outward, indices, lines, grid, cosine):
                continue
            ends.append(
                _End(
                    point,
                    outward,
                    bridge_limit(pieces[index]),
                    style_key(line),
                )
            )
    if not ends:
        return []
    reach = max(end.limit for end in ends)
    end_grid = SegmentGrid([end.point + end.point for end in ends])
    pairs = []
    for position, end in enumerate(ends):
        x, y = end.point
        for other in end_grid.query(x - reach, y - reach, x + reach, y + reach):
            partner = ends[other]
            if other <= position or partner.style != end.style:
                continue
            distance = math.dist(end.point, partner.point)
            if not 0.0 < distance <= max(end.limit, partner.limit):
                continue
            dx = (partner.point[0] - x) / distance
            dy = (partner.point[1] - y) / distance
            if (
                end.outward[0] * dx + end.outward[1] * dy >= cosine
                and partner.outward[0] * dx + partner.outward[1] * dy <= -cosine
            ):
                pairs.append((distance, position, other))
    pairs.sort()
    used: Set[int] = set()
    bridges = []
    for _distance, first, second in pairs:
        if first in used or second in used:
            continue
        used.update((first, second))
        bridges.append(ends[first].point + ends[second].point)
    return bridges


def dashed_components(
    lines: Sequence[LineSegment], boundary: DashedBoundary
) -> List[List[Segment]]:
    indices = sorted(index for index in boundary.pieces if lines[index].length > 0.0)
    grid = SegmentGrid([lines[index].points for index in indices])
    joined = _Union(len(indices))
    owner: Dict[Point, int] = {}
    for position, index in enumerate(indices):
        for point in _ends(lines[index]):
            owner[point] = position
            x, y = point
            for other in grid.query(
                x - DASH_JOIN_PTS,
                y - DASH_JOIN_PTS,
                x + DASH_JOIN_PTS,
                y + DASH_JOIN_PTS,
            ):
                line = lines[indices[other]]
                if (
                    style_key(line) == style_key(lines[index])
                    and point_segment_distance(x, y, *line.points) <= DASH_JOIN_PTS
                ):
                    joined.join(position, other)
    for bridge in boundary.bridges:
        joined.join(owner[bridge[:2]], owner[bridge[2:]])
    members: Dict[int, List[Segment]] = defaultdict(list)
    for position, index in enumerate(indices):
        members[joined.find(position)].append(lines[index].points)
    for bridge in boundary.bridges:
        members[joined.find(owner[bridge[:2]])].append(bridge)
    return list(members.values())


def _continued(
    point: Point,
    outward: Point,
    indices: List[int],
    lines: Sequence[LineSegment],
    grid: SegmentGrid,
    cosine: float,
) -> bool:
    x, y = point
    for other in grid.query(
        x - DASH_JOIN_PTS, y - DASH_JOIN_PTS, x + DASH_JOIN_PTS, y + DASH_JOIN_PTS
    ):
        line = lines[indices[other]]
        if point_segment_distance(x, y, *line.points) > DASH_JOIN_PTS:
            continue
        for end in _ends(line):
            away = math.dist(point, end)
            if away > DASH_JOIN_PTS and (
                (end[0] - x) * outward[0] + (end[1] - y) * outward[1] >= cosine * away
            ):
                return True
    return False
