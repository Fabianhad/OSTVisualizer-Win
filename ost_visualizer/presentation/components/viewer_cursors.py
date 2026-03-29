from PySide6 import QtCore, QtGui
from ..configurators.window_configurator import resource_path

OUTLINE_OFFSETS = [
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, -1),
    (0, 1),
    (1, -1),
    (1, 0),
    (1, 1),
]


def recolor_pixmap(src: QtGui.QPixmap, color: QtGui.QColor) -> QtGui.QPixmap:
    dst = QtGui.QPixmap(src.size())
    dst.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(dst)
    p.drawPixmap(0, 0, src)
    p.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(dst.rect(), color)
    p.end()
    return dst


def _make_outlined_cursor(icon_name: str) -> QtGui.QCursor:
    base = QtGui.QPixmap(resource_path("resources", "icons", icon_name)).scaled(
        24,
        24,
        QtCore.Qt.AspectRatioMode.KeepAspectRatio,
        QtCore.Qt.TransformationMode.SmoothTransformation,
    )
    black = recolor_pixmap(base, QtGui.QColor(0, 0, 0))
    white = recolor_pixmap(base, QtGui.QColor(255, 255, 255))
    pm = QtGui.QPixmap(26, 26)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pm)
    for dx, dy in OUTLINE_OFFSETS:
        painter.drawPixmap(1 + dx, 1 + dy, black)
    painter.drawPixmap(1, 1, white)
    painter.end()
    return QtGui.QCursor(pm, 11, 11)


def make_zoom_cursor() -> QtGui.QCursor:
    return _make_outlined_cursor("search_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg")


def make_rotate_cursor() -> QtGui.QCursor:
    return _make_outlined_cursor("replay_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg")
