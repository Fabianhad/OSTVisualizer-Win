import math

DASH_PATTERN = (13.44, 4.56, 1.44, 4.56)
PATTERN_GAP = 4.56
OUTLINE_WIDTH = 0.6
CORNER_RADIUS = 9.0
CORNER_PIECES = 6
OUTLINE = (100.0, 100.0, 188.44, 264.28)
WALL_OUTER = (106.0, 116.0, 182.0, 252.0)
WALL_INNER = (112.0, 122.0, 176.0, 246.0)
SEED = (144.0, 184.0)


def outline_area(outline=OUTLINE, radius=CORNER_RADIUS) -> float:
    left, top, right, bottom = outline
    return (right - left) * (bottom - top) - (4.0 - math.pi) * radius * radius


def wall_face_area(inner=WALL_INNER) -> float:
    left, top, right, bottom = inner
    return (right - left) * (bottom - top)


def dash_line(start, end, pattern, skip=()):
    length = math.dist(start, end)
    ux = (end[0] - start[0]) / length
    uy = (end[1] - start[1]) / length
    pieces = []
    position = 0.0
    step = 0
    while position < length:
        stop = min(length, position + pattern[step % len(pattern)])
        if step % 2 == 0:
            pieces.append(
                (
                    start[0] + ux * position,
                    start[1] + uy * position,
                    start[0] + ux * stop,
                    start[1] + uy * stop,
                )
            )
        position = stop
        step += 1
    return [piece for index, piece in enumerate(pieces) if index not in skip]


def _arc(cx, cy, radius, first_deg, pieces):
    points = [
        (
            cx + radius * math.cos(math.radians(first_deg + 90.0 * i / pieces)),
            cy + radius * math.sin(math.radians(first_deg + 90.0 * i / pieces)),
        )
        for i in range(pieces + 1)
    ]
    return [a + b for a, b in zip(points, points[1:])]


def outline_segments(
    outline=OUTLINE,
    radius=CORNER_RADIUS,
    pattern=DASH_PATTERN,
    skip_on_top=(),
    pieces=CORNER_PIECES,
):
    left, top, right, bottom = outline
    edges = [
        ((left + radius, top), (right - radius, top), skip_on_top),
        ((right, top + radius), (right, bottom - radius), ()),
        ((right - radius, bottom), (left + radius, bottom), ()),
        ((left, bottom - radius), (left, top + radius), ()),
    ]
    corners = [
        (right - radius, top + radius, 270.0),
        (right - radius, bottom - radius, 0.0),
        (left + radius, bottom - radius, 90.0),
        (left + radius, top + radius, 180.0),
    ]
    dashes = []
    for start, end, skip in edges:
        dashes.extend(dash_line(start, end, pattern, skip))
    arcs = []
    for cx, cy, first in corners:
        arcs.extend(_arc(cx, cy, radius, first, pieces))
    return dashes, arcs


def rect_segments(rect):
    left, top, right, bottom = rect
    corners = [(left, top), (right, top), (right, bottom), (left, bottom)]
    return [a + b for a, b in zip(corners, corners[1:] + corners[:1])]


def wall_segments():
    return rect_segments(WALL_OUTER) + rect_segments(WALL_INNER)


def outline_pdf_content(page_height: float, skip_on_top=()) -> str:
    dashes, arcs = outline_segments(skip_on_top=skip_on_top)
    commands = [f"{OUTLINE_WIDTH} w 0 G"]
    for x1, y1, x2, y2 in dashes:
        commands.append(f"{x1} {page_height - y1} m {x2} {page_height - y2} l S")
    for x1, y1, x2, y2 in arcs:
        commands.append(f"{x1} {page_height - y1} m {x2} {page_height - y2} l S")
    commands.append("2 w")
    for x1, y1, x2, y2 in wall_segments():
        commands.append(f"{x1} {page_height - y1} m {x2} {page_height - y2} l S")
    return "\n".join(commands) + "\n"
