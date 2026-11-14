import logging
import re
from PySide6 import QtCore

_qt_logger = logging.getLogger("ost_visualizer.qt")
_UNREADABLE_MONITOR_CATEGORY = "qt.qpa.screen"
_UNREADABLE_MONITOR_MESSAGE = re.compile(
    r'"Unable to open monitor interface to (?P<display>[^"]+):" '
    r'"Unknown error 0xe0000225\."'
)
_unreadable_monitor_displays = set()


def _unreadable_monitor_display(mode, context, message):
    if mode != QtCore.QtMsgType.QtWarningMsg:
        return None
    if context is None or context.category != _UNREADABLE_MONITOR_CATEGORY:
        return None
    match = _UNREADABLE_MONITOR_MESSAGE.fullmatch(message)
    return match["display"] if match else None


def _qt_message_handler(mode, context, message):
    msg = str(message)
    display = _unreadable_monitor_display(mode, context, msg)
    if display is not None:
        if display not in _unreadable_monitor_displays:
            _unreadable_monitor_displays.add(display)
            _qt_logger.debug(
                "Qt could not read the EDID of monitor %s "
                "(qt.qpa.screen, SetupAPI 0xe0000225); "
                "Qt keeps its fallback screen metrics",
                display,
            )
        return
    if mode == QtCore.QtMsgType.QtWarningMsg:
        _qt_logger.warning(msg)
    elif mode == QtCore.QtMsgType.QtCriticalMsg:
        _qt_logger.error(msg)
    elif mode == QtCore.QtMsgType.QtFatalMsg:
        _qt_logger.critical(msg)


def install_qt_message_handler():
    QtCore.qInstallMessageHandler(_qt_message_handler)
