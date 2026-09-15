import re
import weakref
from dataclasses import dataclass
from typing import Dict, Tuple, Union
from PySide6 import QtCore, QtGui, QtSvg, QtWidgets
from shiboken6 import isValid
from ..configurators.window_configurator import resource_path

_FILL_RE = re.compile(r'fill="[^"]*"')
_ICON_CACHE: Dict[Tuple[str, str], QtGui.QIcon] = {}
ThemedIconTarget = Union[
    QtGui.QAction, QtWidgets.QAbstractButton, QtWidgets.QTreeWidgetItem
]
ThemedIconTargetRef = weakref.ReferenceType[ThemedIconTarget]


@dataclass(frozen=True)
class _IconBinding:
    target_ref: ThemedIconTargetRef
    svg_name: str
    hex_color: str | None = None
    column: int | None = None


_REGISTRY: Dict[Tuple[int, int | None], _IconBinding] = {}


def _discard_dead_targets() -> None:
    for key, entry in tuple(_REGISTRY.items()):
        target = entry.target_ref()
        if target is None or not isValid(target):
            _REGISTRY.pop(key, None)


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


def apply_themed_icon(target: ThemedIconTarget, svg_name: str) -> None:
    _apply_icon(target, svg_name)


def apply_colored_icon(target: ThemedIconTarget, svg_name: str, hex_color: str) -> None:
    _apply_icon(target, svg_name, hex_color=hex_color)


def apply_themed_item_icon(
    target: QtWidgets.QTreeWidgetItem, column: int, svg_name: str
) -> None:
    _apply_icon(target, svg_name, column=column)


def _assign_icon(
    target: ThemedIconTarget, icon: QtGui.QIcon, column: int | None
) -> None:
    if isinstance(target, QtWidgets.QTreeWidgetItem):
        assert column is not None
        tree = target.treeWidget()
        if tree is None:
            target.setIcon(column, icon)
        else:
            with QtCore.QSignalBlocker(tree):
                target.setIcon(column, icon)
    else:
        target.setIcon(icon)


def _apply_icon(
    target: ThemedIconTarget,
    svg_name: str,
    *,
    hex_color: str | None = None,
    column: int | None = None,
) -> None:
    _assign_icon(target, _build_icon(svg_name, hex_color or current_text_hex()), column)
    key = (id(target), column)

    def released(target_ref: ThemedIconTargetRef) -> None:
        current = _REGISTRY.get(key)
        if current is not None and current.target_ref is target_ref:
            _REGISTRY.pop(key, None)

    _REGISTRY[key] = _IconBinding(
        weakref.ref(target, released), svg_name, hex_color, column
    )


def rebuild_all_icons() -> None:
    _ICON_CACHE.clear()
    hex_color = current_text_hex()
    for key, binding in tuple(_REGISTRY.items()):
        target = binding.target_ref()
        if target is None or not isValid(target) or _REGISTRY.get(key) is not binding:
            continue
        _assign_icon(
            target,
            _build_icon(binding.svg_name, binding.hex_color or hex_color),
            binding.column,
        )
    _discard_dead_targets()
