from typing import Callable
from PySide6 import QtCore


class DeferredDialogSaveController(QtCore.QObject):
    DEBOUNCE_MS = 500

    def __init__(
        self,
        save_fn: Callable[[], bool],
        parent: QtCore.QObject | None = None,
        debounce_ms: int = DEBOUNCE_MS,
    ) -> None:
        super().__init__(parent)
        self._save_fn = save_fn
        self._pending = False
        self._flushing = False
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(debounce_ms)
        self._timer.timeout.connect(self.flush)

    @property
    def pending(self) -> bool:
        return self._pending

    def schedule(self) -> None:
        self._pending = True
        self._timer.start()

    def flush(self) -> bool:
        if self._flushing:
            return True
        if not self._pending:
            return True
        self._timer.stop()
        self._flushing = True
        try:
            success = bool(self._save_fn())
        finally:
            self._flushing = False
        if success:
            self._pending = False
        return success

    def cancel(self) -> None:
        self._timer.stop()
        self._pending = False

    def cleanup(self) -> None:
        self.cancel()
        self._save_fn = lambda: True
