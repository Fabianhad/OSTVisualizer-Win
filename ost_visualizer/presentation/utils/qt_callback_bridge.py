import logging
from typing import Callable
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


class OstSignaler(QObject):
    ost_changed = Signal(bool)

    def emit_status(self, active: bool) -> None:
        self.ost_changed.emit(active)


class QtCallbackBridge(QObject):
    callback_ready = Signal(int, bool, str)

    def __init__(self):
        super().__init__()
        self._callbacks: dict[int, Callable] = {}
        self._next_id = 0
        self.callback_ready.connect(self._on_callback_ready)

    def _on_callback_ready(self, callback_id: int, success: bool, message: str):
        callback = self._callbacks.pop(callback_id, None)
        if callback:
            try:
                callback(success, message)
            except Exception as exc:
                logger.exception("Error invoking callback: %s", exc)

    def request_callback(
        self, callback: Callable[[bool, str], None], success: bool, message: str
    ):
        callback_id = self._next_id
        self._next_id += 1
        self._callbacks[callback_id] = callback
        self.callback_ready.emit(callback_id, success, message)
