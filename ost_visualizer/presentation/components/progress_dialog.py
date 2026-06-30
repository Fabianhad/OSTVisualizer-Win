import logging
import os
from typing import Any, Callable, Optional
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QObject, QThread, Signal
from ..config import RELAXED_MARGINS, RELAXED_SPACING

logger = logging.getLogger(__name__)


class ProgressReporter(QObject):
    progress = Signal(str)

    def report(self, description: str) -> None:
        self.progress.emit(description)


class _Worker(QObject):
    finished = Signal(object, object)

    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        error: Optional[Exception] = None
        try:
            result = self._fn()
        except Exception as exc:
            logger.exception("Worker error")
            result = False
            error = exc
        self.finished.emit(result, error)


class ProgressDialog(QtWidgets.QDialog):
    def __init__(
        self,
        filename: str,
        task_fn: Callable[[], Any],
        parent: Optional[QtWidgets.QWidget] = None,
        reporter: Optional[ProgressReporter] = None,
        action_text: str = "Processing",
    ) -> None:
        super().__init__(parent)
        self._task_fn = task_fn
        self._thread: Optional[QThread] = None
        self._worker: Optional[_Worker] = None
        self._reporter = reporter
        self._action_text = action_text
        self._result: Any = None
        self._error: Optional[Exception] = None
        self._cleaned_up = False
        self._started = False
        self._setup_ui(filename)

    def _setup_ui(self, filename: str) -> None:
        self.setWindowTitle("Working...")
        self.setWindowFlags(
            self.windowFlags() & ~QtCore.Qt.WindowType.WindowCloseButtonHint
        )
        self.setModal(True)
        self.setFixedWidth(380)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(*RELAXED_MARGINS)
        layout.setSpacing(RELAXED_SPACING)
        self._label = QtWidgets.QLabel(
            f"{self._action_text} <b>{os.path.basename(filename)}</b>..."
        )
        self._label.setWordWrap(True)
        layout.addWidget(self._label)
        self._progress = QtWidgets.QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(16)
        layout.addWidget(self._progress)

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        if self._started or self._cleaned_up:
            return
        self._started = True
        QtCore.QTimer.singleShot(0, self._start)

    def _start(self) -> None:
        if self._cleaned_up:
            return
        self._worker = _Worker(self._task_fn)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        if self._reporter:
            self._reporter.progress.connect(
                self._on_progress, QtCore.Qt.ConnectionType.QueuedConnection
            )
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_progress(self, description: str) -> None:
        if self._cleaned_up or self._label is None:
            return
        self._label.setText(f"{self._action_text} <b>{description}</b>...")

    def _on_finished(self, result: Any, error: Optional[Exception]) -> None:
        if self._cleaned_up:
            return
        self._result = result
        self._error = error
        if result:
            self.accept()
        else:
            self.reject()

    @property
    def result(self) -> Any:
        return self._result

    @property
    def error(self) -> Optional[Exception]:
        return self._error

    def cleanup(self) -> None:
        if self._cleaned_up:
            return
        self._cleaned_up = True
        if self._thread and self._thread.isRunning():
            self._thread.wait(5000)
        if self._reporter:
            try:
                self._reporter.progress.disconnect(self._on_progress)
            except (TypeError, RuntimeError):
                pass
        self._task_fn = None
        self._worker = None
        self._thread = None
        self._reporter = None
        self._label = None
        self._progress = None

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        event.ignore()
