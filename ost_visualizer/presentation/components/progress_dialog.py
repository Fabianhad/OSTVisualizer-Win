import logging
import os
from typing import Any, Callable, Optional
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QObject, QThread, Signal
from ..config import RELAXED_MARGINS, RELAXED_SPACING

logger = logging.getLogger(__name__)
_DIALOG_WIDTH = 380
_PROGRESS_BAR_WIDTH = 260
_PROGRESS_BAR_HEIGHT = 16
_PROGRESS_TRACK_HEIGHT = 3
_PROGRESS_CHUNK_WIDTH = 38
_PROGRESS_ANIMATION_INTERVAL_MS = 35
_PROGRESS_ANIMATION_STEP = 4


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


class _CenteredBusyProgressBar(QtWidgets.QProgressBar):
    def __init__(self) -> None:
        super().__init__()
        self._offset = _PROGRESS_CHUNK_WIDTH
        self._timer = QtCore.QBasicTimer()
        self.setRange(0, 0)
        self.setTextVisible(False)
        self.setFixedSize(_PROGRESS_BAR_WIDTH, _PROGRESS_BAR_HEIGHT)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start(_PROGRESS_ANIMATION_INTERVAL_MS, self)

    def hideEvent(self, event: QtGui.QHideEvent) -> None:
        self.stop_animation()
        super().hideEvent(event)

    def stop_animation(self) -> None:
        if self._timer.isActive():
            self._timer.stop()

    def timerEvent(self, event: QtCore.QTimerEvent) -> None:
        if event.timerId() != self._timer.timerId():
            super().timerEvent(event)
            return
        self._offset = (
            self._offset + _PROGRESS_ANIMATION_STEP
        ) % self._animation_span()
        self.update()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        try:
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)
            track_rect = self._track_rect()
            painter.fillRect(
                track_rect,
                self.palette().color(QtGui.QPalette.ColorRole.Mid),
            )
            painter.fillRect(
                self._chunk_rect(track_rect).intersected(track_rect),
                self.palette().color(QtGui.QPalette.ColorRole.Highlight),
            )
        finally:
            painter.end()

    def _track_rect(self) -> QtCore.QRect:
        y = self.rect().center().y() - (_PROGRESS_TRACK_HEIGHT // 2)
        return QtCore.QRect(0, y, self.width(), _PROGRESS_TRACK_HEIGHT)

    def _chunk_rect(self, track_rect: QtCore.QRect) -> QtCore.QRect:
        x = self._offset - _PROGRESS_CHUNK_WIDTH
        return QtCore.QRect(
            x,
            track_rect.y(),
            _PROGRESS_CHUNK_WIDTH,
            _PROGRESS_TRACK_HEIGHT,
        )

    def _animation_span(self) -> int:
        return self.width() + _PROGRESS_CHUNK_WIDTH


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
            QtCore.Qt.WindowType.Dialog
            | QtCore.Qt.WindowType.CustomizeWindowHint
            | QtCore.Qt.WindowType.WindowTitleHint
        )
        self.setModal(True)
        self.setSizeGripEnabled(False)
        self.setFixedWidth(_DIALOG_WIDTH)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(*RELAXED_MARGINS)
        layout.setSpacing(RELAXED_SPACING)
        self._label = QtWidgets.QLabel(
            f"{self._action_text} <b>{os.path.basename(filename)}</b>..."
        )
        self._label.setWordWrap(True)
        self._label.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._label)
        self._progress = _CenteredBusyProgressBar()
        layout.addWidget(self._progress, alignment=QtCore.Qt.AlignmentFlag.AlignHCenter)
        self._apply_fixed_size()

    def _apply_fixed_size(self) -> None:
        self.setFixedSize(_DIALOG_WIDTH, self.sizeHint().height())

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
        self._apply_fixed_size()

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
        if isinstance(self._progress, _CenteredBusyProgressBar):
            self._progress.stop_animation()
        self._task_fn = None
        self._worker = None
        self._thread = None
        self._reporter = None
        self._label = None
        self._progress = None

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        event.ignore()
