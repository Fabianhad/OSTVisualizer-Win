from PySide6 import QtCore, QtWidgets


class PopupTrackingComboBox(QtWidgets.QComboBox):
    popup_shown = QtCore.Signal()
    popup_hidden = QtCore.Signal()

    def __init__(self, parent=None, popup_hidden_delay_ms: int = 0):
        super().__init__(parent)
        self._popup_hidden_delay_ms = max(0, int(popup_hidden_delay_ms))
        self._popup_hidden_timer = QtCore.QTimer(self)
        self._popup_hidden_timer.setSingleShot(True)
        self._popup_hidden_timer.timeout.connect(self._emit_popup_hidden)

    def showPopup(self) -> None:
        self._popup_hidden_timer.stop()
        self.popup_shown.emit()
        super().showPopup()

    def hidePopup(self) -> None:
        super().hidePopup()
        if self._popup_hidden_delay_ms:
            self._popup_hidden_timer.start(self._popup_hidden_delay_ms)
            return
        self._emit_popup_hidden()

    def _emit_popup_hidden(self) -> None:
        self.popup_hidden.emit()
