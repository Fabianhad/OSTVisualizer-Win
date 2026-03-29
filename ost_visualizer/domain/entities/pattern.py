NONE = 0
SOLID = 1
HORIZONTAL = 2
VERTICAL = 3
BACKWARD_DIAG = 4
FORWARD_DIAG = 5
CROSSHATCH = 6
DIAG_CROSSHATCH = 7
TRANSPARENT = 8
LINE_PATTERNS = frozenset(
    {HORIZONTAL, VERTICAL, BACKWARD_DIAG, FORWARD_DIAG, CROSSHATCH, DIAG_CROSSHATCH}
)


def get_2d_opacity(pattern: int) -> float:
    if pattern == NONE:
        return 0.0
    if pattern == SOLID:
        return 1.0
    if pattern in LINE_PATTERNS:
        return 0.0
    if pattern == TRANSPARENT:
        return 0.5
    return 0.5


def get_3d_opacity(pattern: int) -> float:
    if pattern == SOLID:
        return 1.0
    if pattern in LINE_PATTERNS or pattern not in range(9):
        return 0.5
    if pattern in (NONE, TRANSPARENT):
        return 0.5
    return 0.5
