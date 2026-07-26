import math
from typing import Optional

from PySide6 import QtCore, QtWidgets


def parse_zoom_percent(text: str) -> Optional[float]:
    value = str(text).strip().rstrip("%")
    try:
        percent = float(value)
    except ValueError:
        return None
    if not math.isfinite(percent) or percent <= 0:
        return None
    return percent


def update_zoom_combo(combo: QtWidgets.QComboBox, factor: float) -> None:
    if not math.isfinite(factor) or factor <= 0:
        return
    line_edit = combo.lineEdit()
    combo_was_blocked = combo.blockSignals(True)
    line_edit_was_blocked = line_edit.blockSignals(True)
    try:
        combo.setCurrentIndex(-1)
        line_edit.setText(f"{int(factor * 100)}%")
    finally:
        line_edit.blockSignals(line_edit_was_blocked)
        combo.blockSignals(combo_was_blocked)


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
