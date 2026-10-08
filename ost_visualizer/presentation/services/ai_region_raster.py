import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple
from PySide6.QtCore import QLineF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen

RASTER_MAX_SIDE_PX = 1200
RASTER_MAX_PX_PER_PT = 4.0
LINE_BATCH = 256
SIMPLIFY_TOLERANCE_PX = 0.75
_FREE = 255
Point = Tuple[float, float]


@dataclass(frozen=True)
class RasterRegion:
    ring: Tuple[Point, ...]
    leak: bool
    width_px: int
    height_px: int


def raster_fill_region(
    segments: Sequence[Tuple[float, float, float, float]],
    bbox: Tuple[float, float, float, float],
    seed: Point,
    pen_width_pts: float,
) -> Optional[RasterRegion]:
    left, top, right, bottom = (float(value) for value in bbox)
    if not (left < seed[0] < right and top < seed[1] < bottom):
        return None
    scale = min(
        RASTER_MAX_PX_PER_PT, RASTER_MAX_SIDE_PX / max(right - left, bottom - top)
    )
    width = min(RASTER_MAX_SIDE_PX, max(1, int(math.ceil((right - left) * scale))))
    height = min(RASTER_MAX_SIDE_PX, max(1, int(math.ceil((bottom - top) * scale))))
    stride = (width + 3) // 4 * 4
    pen_px = max(1.0, float(pen_width_pts) * scale)
    mask = _draw_walls(segments, left, top, scale, width, height, stride, pen_px)
    sx = min(width - 1, int((seed[0] - left) * scale))
    sy = min(height - 1, int((seed[1] - top) * scale))
    if mask[sy * stride + sx] != _FREE:
        return None
    filled, leak = _flood(mask, width, height, stride, sx, sy)
    boundary = _outer_boundary(filled, width, height)
    if len(boundary) < 3:
        return None
    simplified = _simplify_ring(boundary, SIMPLIFY_TOLERANCE_PX)
    grown = _offset_ring(simplified, pen_px / 2.0)
    ring = tuple((x / scale + left, y / scale + top) for x, y in grown)
    return RasterRegion(ring, leak, width, height)


def _draw_walls(segments, left, top, scale, width, height, stride, pen_px) -> bytes:
    buffer = bytearray(b"\xff" * (stride * height))
    image = QImage(buffer, width, height, stride, QImage.Format.Format_Grayscale8)
    painter = QPainter(image)
    pen = QPen(QColor(0, 0, 0))
    pen.setWidthF(pen_px)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    lines = [
        QLineF(
            (x1 - left) * scale,
            (y1 - top) * scale,
            (x2 - left) * scale,
            (y2 - top) * scale,
        )
        for x1, y1, x2, y2 in segments
    ]
    for start in range(0, len(lines), LINE_BATCH):
        painter.drawLines(lines[start : start + LINE_BATCH])
    painter.end()
    return bytes(image.constBits())[: stride * height]


def _flood(mask: bytes, width: int, height: int, stride: int, sx: int, sy: int):
    filled = bytearray(width * height)
    leak = False
    stack = [(sx, sy)]
    while stack:
        x, y = stack.pop()
        mask_row = y * stride
        fill_row = y * width
        if mask[mask_row + x] != _FREE or filled[fill_row + x]:
            continue
        lo = x
        while (
            lo > 0
            and mask[mask_row + lo - 1] == _FREE
            and not filled[fill_row + lo - 1]
        ):
            lo -= 1
        hi = x
        while (
            hi < width - 1
            and mask[mask_row + hi + 1] == _FREE
            and not filled[fill_row + hi + 1]
        ):
            hi += 1
        filled[fill_row + lo : fill_row + hi + 1] = b"\x01" * (hi - lo + 1)
        if lo == 0 or hi == width - 1 or y == 0 or y == height - 1:
            leak = True
        for ny in (y - 1, y + 1):
            if not 0 <= ny < height:
                continue
            other_mask = ny * stride
            other_fill = ny * width
            run = False
            for nx in range(lo, hi + 1):
                free = mask[other_mask + nx] == _FREE and not filled[other_fill + nx]
                if free and not run:
                    stack.append((nx, ny))
                run = free
    return filled, leak


def _outer_boundary(filled: bytearray, width: int, height: int) -> List[Point]:
    outgoing: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}

    def add(start, end):
        outgoing.setdefault(start, []).append(end)

    for y in range(height):
        row = y * width
        x = filled.find(1, row, row + width)
        while x != -1:
            px = x - row
            if y == 0 or not filled[row - width + px]:
                add((px, y), (px + 1, y))
            if px == width - 1 or not filled[row + px + 1]:
                add((px + 1, y), (px + 1, y + 1))
            if y == height - 1 or not filled[row + width + px]:
                add((px + 1, y + 1), (px, y + 1))
            if px == 0 or not filled[row + px - 1]:
                add((px, y + 1), (px, y))
            x = filled.find(1, x + 1, row + width)
    best: List[Point] = []
    while outgoing:
        start = next(iter(outgoing))
        loop = [start]
        current = start
        while True:
            targets = outgoing.get(current)
            if not targets:
                break
            nxt = targets.pop()
            if not targets:
                del outgoing[current]
            if nxt == start:
                break
            loop.append(nxt)
            current = nxt
        if len(loop) > len(best):
            best = [(float(x), float(y)) for x, y in loop]
    return best


def _perpendicular_distance(point: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length == 0.0:
        return math.dist(point, a)
    return abs(dx * (a[1] - point[1]) - dy * (a[0] - point[0])) / length


def _simplify(points: List[Point], tolerance: float) -> List[Point]:
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        worst = -1.0
        index = -1
        for position in range(first + 1, last):
            distance = _perpendicular_distance(
                points[position], points[first], points[last]
            )
            if distance > worst:
                worst, index = distance, position
        if worst > tolerance:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return [point for point, flag in zip(points, keep) if flag]


def _simplify_ring(ring: List[Point], tolerance: float) -> List[Point]:
    far = max(range(len(ring)), key=lambda index: math.dist(ring[0], ring[index]))
    first = _simplify(ring[: far + 1], tolerance)
    second = _simplify(ring[far:] + ring[:1], tolerance)
    return first[:-1] + second[:-1]


def _offset_ring(ring: List[Point], distance: float) -> List[Point]:
    count = len(ring)
    signed = sum(
        ring[i][0] * ring[(i + 1) % count][1] - ring[(i + 1) % count][0] * ring[i][1]
        for i in range(count)
    )
    direction = 1.0 if signed > 0 else -1.0
    result = []
    for index in range(count):
        previous = ring[index - 1]
        current = ring[index]
        following = ring[(index + 1) % count]
        normals = []
        for a, b in ((previous, current), (current, following)):
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy) or 1.0
            normals.append((dy / length * direction, -dx / length * direction))
        nx, ny = normals[0][0] + normals[1][0], normals[0][1] + normals[1][1]
        length = math.hypot(nx, ny)
        if length < 1e-9:
            result.append(current)
            continue
        nx, ny = nx / length, ny / length
        cosine = max(0.3, nx * normals[1][0] + ny * normals[1][1])
        result.append(
            (current[0] + nx * distance / cosine, current[1] + ny * distance / cosine)
        )
    return result
