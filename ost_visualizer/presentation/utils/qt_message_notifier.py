from typing import Optional
from PySide6 import QtCore, QtWidgets
from shiboken6 import isValid
from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from .dialog import delete_later_if_valid

_SEVERITY_MAP = {
    "info": QtWidgets.QMessageBox.Icon.Information,
    "warning": QtWidgets.QMessageBox.Icon.Warning,
    "error": QtWidgets.QMessageBox.Icon.Critical,
}


class QtMessageNotifier(QtCore.QObject):
    _show_message = QtCore.Signal(str, str, QtWidgets.QMessageBox.Icon)
    _set_update_active = QtCore.Signal(bool)

    def __init__(
        self,
        icon_provider: Optional[IWindowIconProvider] = None,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._icon_provider = icon_provider
        self._show_message.connect(self._enqueue_message)
        self._set_update_active.connect(self._on_update_state_changed)
        self._queue: list[tuple[str, str, QtWidgets.QMessageBox.Icon]] = []
        self._update_active = False
        self._default_parent: Optional[QtWidgets.QWidget] = None
        self._current_dialog: Optional[QtWidgets.QMessageBox] = None

    def post_message(self, title: str, message: str, severity: str = "info") -> None:
        icon = _SEVERITY_MAP.get(severity, QtWidgets.QMessageBox.Icon.Information)
        self._show_message.emit(title, message, icon)

    def set_parent(self, parent) -> None:
        self._default_parent = parent

    def set_update_active(self, active: bool) -> None:
        self._set_update_active.emit(active)

    def cleanup(self) -> None:
        try:
            self._show_message.disconnect()
        except (TypeError, RuntimeError):
            pass
        try:
            self._set_update_active.disconnect()
        except (TypeError, RuntimeError):
            pass
        if self._queue:
            self._queue.clear()
        if self._current_dialog is not None:
            dialog = self._current_dialog
            self._current_dialog = None
            try:
                dialog.finished.disconnect()
            except (TypeError, RuntimeError):
                pass
            delete_later_if_valid(dialog)
        self._default_parent = None

    @QtCore.Slot(str, str, QtWidgets.QMessageBox.Icon)
    def _enqueue_message(
        self, title: str, message: str, icon: QtWidgets.QMessageBox.Icon
    ) -> None:
        self._queue.append((title, message, icon))
        self._maybe_show_next()

    @QtCore.Slot(bool)
    def _on_update_state_changed(self, active: bool) -> None:
        self._update_active = active
        if not self._update_active:
            self._maybe_show_next()

    def _maybe_show_next(self) -> None:
        if self._current_dialog is not None and not isValid(self._current_dialog):
            self._current_dialog = None
        if self._current_dialog is not None or self._update_active or not self._queue:
            return
        if self._default_parent is not None and not isValid(self._default_parent):
            self._default_parent = None
            self._queue.clear()
            return
        if self._default_parent is not None and not self._default_parent.isVisible():
            QtCore.QTimer.singleShot(100, self._maybe_show_next)
            return
        title, message, icon = self._queue.pop(0)
        dialog = QtWidgets.QMessageBox(
            icon, title, message, parent=self._default_parent
        )
        if self._icon_provider:
            self._icon_provider.set_window_icon(dialog)
        dialog.finished.connect(self._on_dialog_closed)
        self._current_dialog = dialog
        dialog.show()

    def _on_dialog_closed(self) -> None:
        if self._current_dialog is not None:
            dialog = self._current_dialog
            self._current_dialog = None
            try:
                dialog.finished.disconnect()
            except (TypeError, RuntimeError):
                pass
            delete_later_if_valid(dialog)
        self._maybe_show_next()
