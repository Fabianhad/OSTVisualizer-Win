import ctypes
from PySide6 import QtCore, QtWidgets
from ...domain.aggregates.workspace_state_aggregate import WorkspaceStateAggregate

_GWL_STYLE = -16
_WS_MINIMIZEBOX = 0x00020000
_WS_MAXIMIZEBOX = 0x00010000


def set_initial_window_size(widget, width: int, height: int) -> None:
    widget.resize(width, height)
    widget.setMinimumSize(width, height)


def set_fixed_width_auto_height(widget, width: int) -> None:
    layout = widget.layout()
    layout.activate()
    height = layout.totalHeightForWidth(width)
    if height < 0:
        height = layout.sizeHint().height()
    widget.setFixedSize(width, height)


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


class PersistentDialogWindowState:
    def __init__(
        self,
        widget: QtWidgets.QDialog,
        workspace_state_model: WorkspaceStateAggregate,
        key: str,
        default_size: QtCore.QSize | None = None,
    ) -> None:
        self._widget = widget
        self._workspace_state_model = workspace_state_model
        self._key = key
        widget.setWindowFlag(QtCore.Qt.WindowType.WindowCloseButtonHint, True)
        remove_minimize(widget)
        state = workspace_state_model.state
        saved_size = state.dialog_sizes.get(key)
        if saved_size is not None:
            requested_size = QtCore.QSize(saved_size[0], saved_size[1])
        elif default_size is not None:
            requested_size = default_size
        else:
            layout = widget.layout()
            if layout is not None:
                layout.activate()
            requested_size = widget.sizeHint()
        widget.resize(self._bounded_size(requested_size))
        self._restore_maximized = state.dialog_maximized.get(key, False)
        widget.finished.connect(self._on_finished)

    def apply_show_state(self) -> None:
        remove_minimize(self._widget)
        if self._restore_maximized:
            self._restore_maximized = False
            self._widget.showMaximized()

    def _bounded_size(self, requested_size: QtCore.QSize) -> QtCore.QSize:
        minimum_size = self._widget.minimumSizeHint().expandedTo(QtCore.QSize(1, 1))
        bounded_size = requested_size.expandedTo(minimum_size)
        screen = self._widget.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return bounded_size
        available_size = screen.availableGeometry().size()
        return QtCore.QSize(
            min(bounded_size.width(), available_size.width()),
            min(bounded_size.height(), available_size.height()),
        )

    def _on_finished(self, _result: int) -> None:
        normal_geometry = self._widget.normalGeometry()
        size = (
            normal_geometry.size() if normal_geometry.isValid() else self._widget.size()
        )
        stored_size = [size.width(), size.height()]
        stored_maximized = self._widget.isMaximized()
        state = self._workspace_state_model.state
        if (
            state.dialog_sizes.get(self._key) == stored_size
            and state.dialog_maximized.get(self._key) == stored_maximized
        ):
            return
        state.dialog_sizes[self._key] = stored_size
        state.dialog_maximized[self._key] = stored_maximized
        try:
            self._workspace_state_model.update_state(state)
        except OSError:
            return
