import logging
from typing import Optional
from PySide6 import QtCore, QtGui, QtWidgets
from ..config import SPLASH_MESSAGE_MARGIN, SPLASH_SCREEN_HEIGHT, SPLASH_SCREEN_WIDTH
from ..utils.theme import (
    get_app_mid_color,
    get_app_window_color,
    get_app_window_text_color,
    get_splash_message_font,
    get_splash_title_font,
)

logger = logging.getLogger(__name__)


class SplashScreen(QtWidgets.QSplashScreen):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        pixmap = QtGui.QPixmap(SPLASH_SCREEN_WIDTH, SPLASH_SCREEN_HEIGHT)
        pixmap.fill(get_app_window_color())
        super().__init__(pixmap, QtCore.Qt.WindowType.WindowStaysOnTopHint)
        self._title = "OST Visualizer"
        self._message = ""

    def drawContents(self, painter: QtGui.QPainter) -> None:
        text_color = get_app_window_text_color()
        dim_color = get_app_mid_color()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        title_font = get_splash_title_font()
        painter.setFont(title_font)
        painter.setPen(text_color)
        fm = QtGui.QFontMetrics(title_font)
        title_rect = QtCore.QRect(
            0, SPLASH_SCREEN_HEIGHT // 3, SPLASH_SCREEN_WIDTH, fm.height()
        )
        painter.drawText(title_rect, QtCore.Qt.AlignmentFlag.AlignCenter, self._title)
        if self._message:
            message_font = get_splash_message_font()
            painter.setFont(message_font)
            painter.setPen(dim_color)
            fm2 = QtGui.QFontMetrics(message_font)
            message_rect = QtCore.QRect(
                0,
                SPLASH_SCREEN_HEIGHT - fm2.height() - SPLASH_MESSAGE_MARGIN,
                SPLASH_SCREEN_WIDTH,
                fm2.height(),
            )
            painter.drawText(
                message_rect, QtCore.Qt.AlignmentFlag.AlignCenter, self._message
            )

    def cleanup(self) -> None:
        try:
            self.close()
        except RuntimeError:
            logger.exception("Error closing SplashScreen")
        self._title = None
        self._message = None
