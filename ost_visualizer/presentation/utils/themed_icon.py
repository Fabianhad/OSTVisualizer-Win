import re
from typing import Dict, List, Tuple, Union
from PySide6 import QtCore, QtGui, QtSvg, QtWidgets
from ..configurators.window_configurator import resource_path

_FILL_RE = re.compile(r'fill="[^"]*"')
_ICON_CACHE: Dict[Tuple[str, str], QtGui.QIcon] = {}
_REGISTRY: List[Tuple[Union[QtGui.QAction, QtWidgets.QAbstractButton], str]] = []


def current_text_hex() -> str:
    app = QtWidgets.QApplication.instance()
    if app:
        color = app.palette().color(QtGui.QPalette.ColorRole.WindowText)
        return color.name()
    return "#000000"


def recolor_svg(svg_path: str, hex_color: str) -> bytes:
    with open(svg_path, "r", encoding="utf-8") as f:
        svg_text = f.read()
    recolored = _FILL_RE.sub(f'fill="{hex_color}"', svg_text)
    return recolored.encode("utf-8")


def _build_icon(svg_name: str, hex_color: str) -> QtGui.QIcon:
    key = (svg_name, hex_color)
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
    svg_path = resource_path("resources", "icons", svg_name)
    svg_data = recolor_svg(svg_path, hex_color)
    renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(svg_data))
    pixmap = QtGui.QPixmap(renderer.defaultSize())
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    icon = QtGui.QIcon(pixmap)
    _ICON_CACHE[key] = icon
    return icon


def build_colored_icon(svg_name: str, hex_color: str) -> QtGui.QIcon:
    return _build_icon(svg_name, hex_color)


def themed_icon(svg_name: str) -> QtGui.QIcon:
    return _build_icon(svg_name, current_text_hex())


def apply_themed_icon(
    target: Union[QtGui.QAction, QtWidgets.QAbstractButton], svg_name: str
) -> None:
    target.setIcon(themed_icon(svg_name))
    _REGISTRY.append((target, svg_name))


def rebuild_all_icons() -> None:
    _ICON_CACHE.clear()
    hex_color = current_text_hex()
    alive = []
    for target, svg_name in _REGISTRY:
        try:
            target.setIcon(_build_icon(svg_name, hex_color))
            alive.append((target, svg_name))
        except RuntimeError:
            pass
    _REGISTRY.clear()
    _REGISTRY.extend(alive)
