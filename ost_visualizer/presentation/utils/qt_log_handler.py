import logging
from PySide6 import QtCore

_qt_logger = logging.getLogger("ost_visualizer.qt")


def _qt_message_handler(mode, _, message):
    msg = str(message)
    if mode == QtCore.QtMsgType.QtWarningMsg:
        _qt_logger.warning(msg)
    elif mode == QtCore.QtMsgType.QtCriticalMsg:
        _qt_logger.error(msg)
    elif mode == QtCore.QtMsgType.QtFatalMsg:
        _qt_logger.critical(msg)


def install_qt_message_handler():
    QtCore.qInstallMessageHandler(_qt_message_handler)
