from typing import Callable, Optional
from PySide6 import QtGui, QtWidgets
from ..config import (
    DIALOG_HEADER_FONT_SIZE,
    SPLASH_MESSAGE_FONT_SIZE,
    SPLASH_TITLE_FONT_SIZE,
)


def _get_window_color_from_palette(widget: QtWidgets.QWidget) -> QtGui.QColor:
    return widget.palette().color(QtGui.QPalette.ColorRole.Window)


def _get_palette() -> Optional[QtGui.QPalette]:
    app = QtWidgets.QApplication.instance()
    return app.palette() if app else None


def get_app_window_color() -> QtGui.QColor:
    palette = _get_palette()
    if palette:
        return palette.color(QtGui.QPalette.ColorRole.Window)
    return QtGui.QColor(240, 240, 240)


def get_app_window_text_color() -> QtGui.QColor:
    palette = _get_palette()
    if palette:
        return palette.color(QtGui.QPalette.ColorRole.WindowText)
    return QtGui.QColor(0, 0, 0)


def get_app_mid_color() -> QtGui.QColor:
    palette = _get_palette()
    if palette:
        return palette.color(QtGui.QPalette.ColorRole.Mid)
    return QtGui.QColor(120, 120, 120)


def get_dialog_header_font() -> QtGui.QFont:
    font = QtGui.QFont()
    font.setPointSize(DIALOG_HEADER_FONT_SIZE)
    font.setWeight(QtGui.QFont.Weight.Bold)
    return font


def get_splash_title_font() -> QtGui.QFont:
    font = QtGui.QFont()
    font.setPointSize(SPLASH_TITLE_FONT_SIZE)
    font.setBold(True)
    return font


def get_splash_message_font() -> QtGui.QFont:
    font = QtGui.QFont()
    font.setPointSize(SPLASH_MESSAGE_FONT_SIZE)
    return font


def set_palette_background(
    widget: QtWidgets.QWidget, setter: Callable[[QtGui.QColor], None]
) -> None:
    window_color = _get_window_color_from_palette(widget)
    setter(window_color)
