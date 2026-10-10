import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

KIND_WALL = "wall"
KIND_DASHED = "dashed"
KIND_THIN = "thin"
KIND_SYMBOL = "symbol"
LINE_KINDS = (KIND_WALL, KIND_DASHED, KIND_THIN, KIND_SYMBOL)
SYMBOL_MAX_PTS = 48.0
HEAVY_MIN_WIDTH_PTS = 0.95
HEAVY_WIDTH_RATIO = 1.5
DASH_PIECE_MAX_PTS = 18.0
DASH_GAP_MAX_PTS = 18.0
DASH_GAP_MIN_PTS = 0.2
DASH_MIN_PIECES = 3
DASH_ANGLE_TOLERANCE_DEG = 2.0
DASH_OFFSET_TOLERANCE_PTS = 0.5
DASH_NEIGHBOUR_LIMIT = 128
SUGGESTED_MIN_KEPT = 20
PEN_STEP_MIN_RATIO = 1.3
LIGHT_PEN_MIN_SHARE = 0.2
HEAVY_PEN_MIN_SHARE = 0.1
WIDTH_SUGGESTED = "suggested"
WIDTH_NO_STROKE_WIDTHS = "no_stroke_widths"
WIDTH_SINGLE_PEN = "single_pen"
WIDTH_NO_CLEAR_PEN_STEP = "no_clear_pen_step"
WIDTH_LIGHT_PENS_TOO_RARE = "light_pens_too_rare"
WIDTH_HEAVY_PENS_TOO_RARE = "heavy_pens_too_rare"
WIDTH_TOO_FEW_HEAVY_LINES = "too_few_heavy_lines"
WIDTH_CLASS_DECIMALS = 2
_COMPACT_RATIO = 0.25
_TINY_FRACTION = 0.25
_MAX_GRID_SIDE = 512
_MAX_CELLS_PER_SEGMENT = 4096
Point = Tuple[float, float]
Box = Tuple[float, float, float, float]


@dataclass(frozen=True)
class LineSegment:
    x1: float
    y1: float
    x2: float
    y2: float
    width: Optional[float] = None
    dash: Tuple[float, ...] = ()
    color: str = ""
    stroked: bool = True
    filled: bool = False
    closed: bool = False
    curve: bool = False
    group: str = ""

    @property
    def points(self) -> Tuple[float, float, float, float]:
        return (float(self.x1), float(self.y1), float(self.x2), float(self.y2))

    @property
    def length(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)

    @property
    def has_dash(self) -> bool:
        return sum(self.dash) > 0.0


def rgba_hex(rgba: Optional[int]) -> str:
    if rgba is None:
        return ""
    return f"#{(int(rgba) >> 8) & 0xFFFFFF:06x}"


def is_symbol_box(box: Box, symbol_max: float) -> bool:
    if symbol_max <= 0.0:
        return False
    width = abs(box[2] - box[0])
    height = abs(box[3] - box[1])
    longest = max(width, height)
    if longest >= symbol_max:
        return False
    return longest < symbol_max * _TINY_FRACTION or min(width, height) >= (
        _COMPACT_RATIO * longest
    )


def symbol_groups(
    segments: Sequence[LineSegment], symbol_max: float = SYMBOL_MAX_PTS
) -> Dict[str, Box]:
    boxes: Dict[str, List[float]] = {}
    for segment in segments:
        if not segment.closed or not segment.group:
            continue
        box = boxes.get(segment.group)
        xs = (segment.x1, segment.x2)
        ys = (segment.y1, segment.y2)
        if box is None:
            boxes[segment.group] = [min(xs), min(ys), max(xs), max(ys)]
            continue
        box[0] = min(box[0], *xs)
        box[1] = min(box[1], *ys)
        box[2] = max(box[2], *xs)
        box[3] = max(box[3], *ys)
    return {
        group: (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
        for group, box in boxes.items()
        if is_symbol_box(box, symbol_max)
    }


def heavy_width_threshold(segments: Sequence[LineSegment]) -> float:
    widths = [
        float(segment.width)
        for segment in segments
        if segment.stroked and segment.width is not None
    ]
    if not widths:
        return HEAVY_MIN_WIDTH_PTS
    return max(HEAVY_MIN_WIDTH_PTS, HEAVY_WIDTH_RATIO * statistics.median(widths))


@dataclass(frozen=True)
class WidthSuggestion:
    width: Optional[float]
    reason: str


@dataclass(frozen=True)
class _PenClasses:
    keys: Tuple[float, ...]
    lengths: Dict[float, float]
    counts: Dict[float, int]
    lightest: Dict[float, float]
    heaviest: Dict[float, float]
    bulk: Optional[float]
    heavy: Tuple[float, ...]


def _pen_classes(segments: Sequence[LineSegment]) -> _PenClasses:
    lengths: Dict[float, float] = defaultdict(float)
    lightest: Dict[float, float] = {}
    heaviest: Dict[float, float] = {}
    counts: Dict[float, int] = defaultdict(int)
    for segment in segments:
        if not segment.stroked or segment.width is None or segment.has_dash:
            continue
        width = float(segment.width)
        length = segment.length
        if not (math.isfinite(width) and width > 0.0 and math.isfinite(length)):
            continue
        if length <= 0.0:
            continue
        key = round(width, WIDTH_CLASS_DECIMALS)
        lengths[key] += length
        counts[key] += 1
        lightest[key] = min(lightest.get(key, width), width)
        heaviest[key] = max(heaviest.get(key, width), width)
    keys = tuple(sorted(lengths))
    bulk = None
    heavy: Tuple[float, ...] = ()
    if len(keys) > 1:
        total = sum(lengths.values())
        covered = 0.0
        bulk = keys[-1]
        for key in keys:
            covered += lengths[key]
            if covered >= LIGHT_PEN_MIN_SHARE * total:
                bulk = key
                break
        cutoff = PEN_STEP_MIN_RATIO * heaviest[bulk]
        heavy = tuple(key for key in keys if lightest[key] >= cutoff)
    return _PenClasses(keys, lengths, counts, lightest, heaviest, bulk, heavy)


def width_suggestion(segments: Sequence[LineSegment]) -> WidthSuggestion:
    pens = _pen_classes(segments)
    if not pens.keys:
        return WidthSuggestion(None, WIDTH_NO_STROKE_WIDTHS)
    if len(pens.keys) == 1:
        return WidthSuggestion(None, WIDTH_SINGLE_PEN)
    if not pens.heavy:
        lighter = any(
            PEN_STEP_MIN_RATIO * pens.heaviest[key] <= pens.lightest[pens.bulk]
            for key in pens.keys
            if key < pens.bulk
        )
        return WidthSuggestion(
            None, WIDTH_LIGHT_PENS_TOO_RARE if lighter else WIDTH_NO_CLEAR_PEN_STEP
        )
    total = sum(pens.lengths.values())
    heavy_length = sum(pens.lengths[key] for key in pens.heavy)
    heavy_count = sum(pens.counts[key] for key in pens.heavy)
    if heavy_length < HEAVY_PEN_MIN_SHARE * total:
        return WidthSuggestion(None, WIDTH_HEAVY_PENS_TOO_RARE)
    if heavy_count < SUGGESTED_MIN_KEPT:
        return WidthSuggestion(None, WIDTH_TOO_FEW_HEAVY_LINES)
    return WidthSuggestion(pens.lightest[pens.heavy[0]], WIDTH_SUGGESTED)


def wall_width_threshold(segments: Sequence[LineSegment]) -> float:
    pens = _pen_classes(segments)
    if pens.heavy:
        return pens.lightest[pens.heavy[0]]
    return heavy_width_threshold(segments)


def suggested_min_width(segments: Sequence[LineSegment]) -> Optional[float]:
    return width_suggestion(segments).width


def classify_linework(
    segments: Sequence[LineSegment], symbol_max: float = SYMBOL_MAX_PTS
) -> List[str]:
    symbols = symbol_groups(segments, symbol_max)
    exploded = _exploded_dashes(segments)
    heavy = wall_width_threshold(segments)
    heavy_curve = heavy_width_threshold(segments)
    kinds = []
    for index, segment in enumerate(segments):
        threshold = heavy_curve if segment.curve else heavy
        if segment.closed and segment.group in symbols:
            kinds.append(KIND_SYMBOL)
        elif segment.has_dash or index in exploded:
            kinds.append(KIND_DASHED)
        elif not segment.stroked:
            kinds.append(KIND_WALL)
        elif segment.width is not None and segment.width >= threshold:
            kinds.append(KIND_WALL)
        else:
            kinds.append(KIND_THIN)
    return kinds


def _direction(segment: LineSegment) -> Tuple[float, float]:
    length = segment.length
    return (segment.x2 - segment.x1) / length, (segment.y2 - segment.y1) / length


def collinear_gap(first: LineSegment, second: LineSegment) -> Optional[float]:
    ux, uy = _direction(first)
    vx, vy = _direction(second)
    if abs(ux * vy - uy * vx) > math.sin(math.radians(DASH_ANGLE_TOLERANCE_DEG)):
        return None
    for x, y in ((second.x1, second.y1), (second.x2, second.y2)):
        if abs((x - first.x1) * uy - (y - first.y1) * ux) > DASH_OFFSET_TOLERANCE_PTS:
            return None
    a_low, a_high = _projection(first, first.x1, first.y1, ux, uy)
    b_low, b_high = _projection(second, first.x1, first.y1, ux, uy)
    return max(b_low - a_high, a_low - b_high)


def _projection(
    segment: LineSegment, ox: float, oy: float, ux: float, uy: float
) -> Tuple[float, float]:
    start = (segment.x1 - ox) * ux + (segment.y1 - oy) * uy
    end = (segment.x2 - ox) * ux + (segment.y2 - oy) * uy
    return min(start, end), max(start, end)


def _exploded_dashes(segments: Sequence[LineSegment]) -> set:
    candidates = [
        index
        for index, segment in enumerate(segments)
        if not segment.has_dash
        and not segment.closed
        and 0.0 < segment.length <= DASH_PIECE_MAX_PTS
    ]
    if len(candidates) < DASH_MIN_PIECES:
        return set()
    grid = SegmentGrid([segments[index].points for index in candidates])
    parent = list(range(len(candidates)))

    def find(item: int) -> int:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    reach = DASH_GAP_MAX_PTS + DASH_OFFSET_TOLERANCE_PTS
    cells = [_density_cell(segments[index], reach) for index in candidates]
    counts: Dict[Tuple[int, int], int] = defaultdict(int)
    for cell in cells:
        counts[cell] += 1
    solid = set()
    for position, index in enumerate(candidates):
        column, row = cells[position]
        crowd = sum(
            counts.get((column + dx, row + dy), 0)
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
        )
        if crowd > DASH_NEIGHBOUR_LIMIT:
            solid.add(position)
            continue
        segment = segments[index]
        left = min(segment.x1, segment.x2) - reach
        top = min(segment.y1, segment.y2) - reach
        right = max(segment.x1, segment.x2) + reach
        bottom = max(segment.y1, segment.y2) + reach
        for other in grid.query(left, top, right, bottom):
            if other <= position:
                continue
            gap = collinear_gap(segment, segments[candidates[other]])
            if gap is None or gap > DASH_GAP_MAX_PTS + 1e-9:
                continue
            if gap < DASH_GAP_MIN_PTS:
                solid.update((position, other))
            parent[find(other)] = find(position)
    sizes: Dict[int, int] = defaultdict(int)
    for position in range(len(candidates)):
        sizes[find(position)] += 1
    touching = {find(position) for position in solid}
    return {
        index
        for position, index in enumerate(candidates)
        if sizes[find(position)] >= DASH_MIN_PIECES and find(position) not in touching
    }


def _density_cell(segment: LineSegment, size: float) -> Tuple[int, int]:
    return (
        int(math.floor((segment.x1 + segment.x2) / 2.0 / size)),
        int(math.floor((segment.y1 + segment.y2) / 2.0 / size)),
    )


class SegmentGrid:
    def __init__(self, segments: Sequence[Tuple[float, float, float, float]]):
        self._segments = [
            tuple(float(value) for value in segment) for segment in segments
        ]
        self._cells: Dict[Tuple[int, int], List[int]] = defaultdict(list)
        self._wide: List[int] = []
        self._cell = 1.0
        self._origin = (0.0, 0.0)
        if not self._segments:
            return
        xs = [value for x1, _y1, x2, _y2 in self._segments for value in (x1, x2)]
        ys = [value for _x1, y1, _x2, y2 in self._segments for value in (y1, y2)]
        side = min(_MAX_GRID_SIDE, max(1, math.ceil(math.sqrt(len(self._segments)))))
        extent = max(max(xs) - min(xs), max(ys) - min(ys))
        self._cell = max(extent / side, 1e-6)
        self._origin = (min(xs), min(ys))
        for index, (x1, y1, x2, y2) in enumerate(self._segments):
            c0, r0 = self._cell_of(min(x1, x2), min(y1, y2))
            c1, r1 = self._cell_of(max(x1, x2), max(y1, y2))
            if (c1 - c0 + 1) * (r1 - r0 + 1) > _MAX_CELLS_PER_SEGMENT:
                self._wide.append(index)
                continue
            for column in range(c0, c1 + 1):
                for row in range(r0, r1 + 1):
                    self._cells[(column, row)].append(index)

    def _cell_of(self, x: float, y: float) -> Tuple[int, int]:
        return (
            int(math.floor((x - self._origin[0]) / self._cell)),
            int(math.floor((y - self._origin[1]) / self._cell)),
        )

    def query(self, left: float, top: float, right: float, bottom: float) -> List[int]:
        if not self._segments:
            return []
        c0, r0 = self._cell_of(left, top)
        c1, r1 = self._cell_of(right, bottom)
        found = set(self._wide)
        if (c1 - c0 + 1) * (r1 - r0 + 1) > len(self._cells):
            for members in self._cells.values():
                found.update(members)
        else:
            for column in range(c0, c1 + 1):
                for row in range(r0, r1 + 1):
                    found.update(self._cells.get((column, row), ()))
        return sorted(found)

    def segment(self, index: int) -> Tuple[float, float, float, float]:
        return self._segments[index]

    def distance(self, point: Point, max_distance: float) -> float:
        x, y = point
        best = math.inf
        for index in self.query(
            x - max_distance, y - max_distance, x + max_distance, y + max_distance
        ):
            x1, y1, x2, y2 = self._segments[index]
            best = min(best, point_segment_distance(x, y, x1, y1, x2, y2))
        return best if best <= max_distance else math.inf


def point_segment_distance(
    x: float, y: float, x1: float, y1: float, x2: float, y2: float
) -> float:
    dx = x2 - x1
    dy = y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq == 0.0:
        return math.hypot(x - x1, y - y1)
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / length_sq))
    return math.hypot(x - x1 - t * dx, y - y1 - t * dy)


def _ring_samples(ring: Sequence[Point], step: float) -> List[Point]:
    samples = []
    count = len(ring)
    for index in range(count):
        start = ring[index]
        end = ring[(index + 1) % count]
        pieces = max(1, int(math.ceil(math.dist(start, end) / step)))
        for piece in range(pieces):
            t = piece / pieces
            samples.append(
                (start[0] + t * (end[0] - start[0]), start[1] + t * (end[1] - start[1]))
            )
    return samples


def uncovered_runs(
    ring: Sequence[Point], grid: SegmentGrid, tolerance: float, max_chord: float
) -> List[Tuple[Point, Point, float]]:
    if len(ring) < 3 or tolerance <= 0.0:
        return []
    samples = _ring_samples(ring, tolerance / 2.0)
    covered = [grid.distance(sample, tolerance) <= tolerance for sample in samples]
    if all(covered) or not any(covered):
        return []
    first = covered.index(True)
    order = samples[first:] + samples[:first]
    flags = covered[first:] + covered[:first]
    runs = []
    position = 0
    count = len(order)
    while position < count:
        if flags[position]:
            position += 1
            continue
        start = order[position - 1]
        while position < count and not flags[position]:
            position += 1
        end = order[position % count]
        chord = math.dist(start, end)
        if 2.0 * tolerance < chord <= max_chord:
            runs.append((start, end, chord))
    return runs
