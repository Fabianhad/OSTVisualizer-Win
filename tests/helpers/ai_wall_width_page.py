WALL_WIDTH = 0.66
HEAVY_WIDTH = 1.02
THIN_WIDTH = 0.25
ROOM_COLUMNS = 4
ROOM_ROWS = 3
ROOM_WIDTH = 150.0
ROOM_HEIGHT = 120.0
ORIGIN = (100.0, 100.0)
HEAVY_LINE_COUNT = 24
THIN_LINE_COUNT = 1000


def _rect(x1, y1, x2, y2):
    return [(x1, y1, x2, y1), (x2, y1, x2, y2), (x2, y2, x1, y2), (x1, y2, x1, y1)]


def wall_width_page():
    """An S101-like sheet: 0.66 pt walls between a 0.25 pt bulk and 1.02 pt frames.
    Returns (x1, y1, x2, y2, width) tuples. The 0.66 pt walls enclose
    ROOM_COLUMNS x ROOM_ROWS rooms. The 1.02 pt lines are the sheet frame and
    column grid lines outside the rooms, and the 0.25 pt lines are dimension
    and leader strokes that stay outside the rooms too.
    """
    left, top = ORIGIN
    walls = []
    for column in range(ROOM_COLUMNS):
        for row in range(ROOM_ROWS):
            x = left + column * ROOM_WIDTH
            y = top + row * ROOM_HEIGHT
            walls += _rect(x, y, x + ROOM_WIDTH, y + ROOM_HEIGHT)
    right = left + ROOM_COLUMNS * ROOM_WIDTH
    bottom = top + ROOM_ROWS * ROOM_HEIGHT
    heavy = []
    for index in range(HEAVY_LINE_COUNT):
        y = bottom + 60.0 + index * 4.0
        heavy.append((left - 40.0, y, right + 40.0, y))
    thin = []
    for index in range(THIN_LINE_COUNT):
        y = bottom + 200.0 + (index // 10) * 3.0
        x = left + (index % 10) * 64.0
        thin.append((x, y, x + 60.0, y))
    return (
        [(*segment, WALL_WIDTH) for segment in walls]
        + [(*segment, HEAVY_WIDTH) for segment in heavy]
        + [(*segment, THIN_WIDTH) for segment in thin]
    )
