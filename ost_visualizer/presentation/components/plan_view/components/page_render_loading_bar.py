from PySide6 import QtCore
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


class PageRenderLoadingBar(QWidget):
    _REVEAL_DELAY_MS = 120
    _ANIMATION_INTERVAL_MS = 80
    _HEIGHT = 3

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(self._HEIGHT)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.hide()
        self._active_token: str | None = None
        self._progress = 0.0
        self._reveal_timer = QtCore.QTimer(self)
        self._reveal_timer.setSingleShot(True)
        self._reveal_timer.timeout.connect(self._show_for_active_token)
        self._animation_timer = QtCore.QTimer(self)
        self._animation_timer.setInterval(self._ANIMATION_INTERVAL_MS)
        self._animation_timer.timeout.connect(self._advance_progress)

    @property
    def is_loading(self) -> bool:
        return self._active_token is not None

    def start(self, token: str) -> None:
        self._active_token = token
        self._progress = 0.08
        self.hide()
        self._animation_timer.stop()
        self._reveal_timer.start(self._REVEAL_DELAY_MS)

    def complete(self, token: str) -> None:
        if token != self._active_token:
            return
        self.reset(token)

    def reset(self, token: str | None = None) -> None:
        if token is not None and token != self._active_token:
            return
        self._active_token = None
        self._progress = 0.0
        self._reveal_timer.stop()
        self._animation_timer.stop()
        self.hide()
        self.update()

    def _show_for_active_token(self) -> None:
        if self._active_token is None:
            return
        self.show()
        self.raise_()
        self._animation_timer.start()
        self.update()

    def _advance_progress(self) -> None:
        if self._active_token is None:
            self.reset()
            return
        if self._progress < 0.82:
            self._progress += 0.08
        else:
            self._progress = 0.28
        self.update()

    def paintEvent(self, event) -> None:
        del event
        if self._active_token is None:
            return
        painter = QPainter(self)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QColor(78, 138, 190))
        width = max(1, int(self.width() * self._progress))
        painter.drawRect(0, 0, width, self.height())
