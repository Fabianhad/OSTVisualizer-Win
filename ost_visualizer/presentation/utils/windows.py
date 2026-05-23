import ctypes
from PySide6 import QtCore

_GWL_STYLE = -16
_WS_MINIMIZEBOX = 0x00020000
_WS_MAXIMIZEBOX = 0x00010000


def set_initial_window_size(widget, width: int, height: int) -> None:
    widget.resize(width, height)
    widget.setMinimumSize(width, height)


def _set_qt_window_button_hints(
    widget, *, allow_minimize: bool, allow_maximize: bool
) -> None:
    if widget.isVisible():
        return
    widget.setWindowFlag(QtCore.Qt.WindowType.WindowMinimizeButtonHint, allow_minimize)
    widget.setWindowFlag(QtCore.Qt.WindowType.WindowMaximizeButtonHint, allow_maximize)


def _remove_windows_style_bits(widget, bits: int) -> None:
    try:
        hwnd = int(widget.winId())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_STYLE)
        ctypes.windll.user32.SetWindowLongW(hwnd, _GWL_STYLE, style & ~bits)
    except (AttributeError, OSError, RuntimeError, ValueError):
        pass


def remove_minimize_maximize(widget) -> None:
    _set_qt_window_button_hints(widget, allow_minimize=False, allow_maximize=False)
    _remove_windows_style_bits(widget, _WS_MINIMIZEBOX | _WS_MAXIMIZEBOX)


def remove_minimize(widget) -> None:
    _set_qt_window_button_hints(widget, allow_minimize=False, allow_maximize=True)
    _remove_windows_style_bits(widget, _WS_MINIMIZEBOX)
