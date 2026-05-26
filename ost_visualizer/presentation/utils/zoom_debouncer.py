from PySide6.QtCore import QObject, QTimer, Signal

ZOOM_SETTLE_DELAY_MS = 125


class ZoomDebouncer(QObject):
    zoom_settled = Signal(float)

    def __init__(self, delay_ms: int = ZOOM_SETTLE_DELAY_MS, parent=None):
        super().__init__(parent)
        self._pending_scale: float = 1.0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._on_settled)

    def handle_scale_changed(self, new_view_m11: float) -> None:
        self._pending_scale = new_view_m11
        self._timer.start()

    def cancel(self) -> None:
        self._timer.stop()

    def _on_settled(self) -> None:
        self.zoom_settled.emit(self._pending_scale)
