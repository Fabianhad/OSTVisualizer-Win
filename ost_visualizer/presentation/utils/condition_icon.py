from PySide6 import QtGui
from ...domain.entities import pattern as _pattern

COLOR_BOX_SIZE = 12


def _is_fill_pixel(pattern: int, row: int, col: int) -> bool:
    if pattern == _pattern.SOLID:
        return True
    if pattern == _pattern.HORIZONTAL:
        return row % 4 == 0
    if pattern == _pattern.VERTICAL:
        return col % 4 == 0
    if pattern == _pattern.BACKWARD_DIAG:
        return (row - col) % 4 == 0
    if pattern == _pattern.FORWARD_DIAG:
        return (row + col) % 4 == 0
    if pattern == _pattern.CROSSHATCH:
        return row % 4 == 0 or col % 4 == 0
    if pattern == _pattern.DIAG_CROSSHATCH:
        return (row - col) % 4 == 0 or (row + col) % 4 == 0
    if pattern == _pattern.TRANSPARENT:
        return (row + col) % 2 == 0
    return False


def make_condition_color_icon(
    color_int: int, pattern: int = _pattern.SOLID, grayscale: bool = False
) -> QtGui.QIcon:
    r = color_int & 0xFF
    g = (color_int >> 8) & 0xFF
    b = (color_int >> 16) & 0xFF
    if grayscale:
        gray = int(0.299 * r + 0.587 * g + 0.114 * b)
        r, g, b = gray, gray, gray
    fill_rgb = QtGui.QColor(r, g, b).rgb()
    bg_rgb = QtGui.QColor(255, 255, 255).rgb()
    image = QtGui.QImage(
        COLOR_BOX_SIZE, COLOR_BOX_SIZE, QtGui.QImage.Format.Format_RGB32
    )
    for row in range(COLOR_BOX_SIZE):
        for col in range(COLOR_BOX_SIZE):
            image.setPixel(
                col, row, fill_rgb if _is_fill_pixel(pattern, row, col) else bg_rgb
            )
    return QtGui.QIcon(QtGui.QPixmap.fromImage(image))
