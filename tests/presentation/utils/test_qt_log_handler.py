import unittest
from unittest.mock import patch
from PySide6 import QtCore
from ost_visualizer.presentation.utils import qt_log_handler


class QtLogHandlerTests(unittest.TestCase):
    def test_warning_critical_and_fatal_preserve_severity_without_logging_debug(self):
        with patch.object(qt_log_handler, "_qt_logger") as logger:
            qt_log_handler._qt_message_handler(
                QtCore.QtMsgType.QtWarningMsg, None, "warning"
            )
            qt_log_handler._qt_message_handler(
                QtCore.QtMsgType.QtCriticalMsg, None, "error"
            )
            qt_log_handler._qt_message_handler(
                QtCore.QtMsgType.QtFatalMsg, None, "fatal"
            )
            qt_log_handler._qt_message_handler(
                QtCore.QtMsgType.QtDebugMsg, None, "debug"
            )
            logger.warning.assert_called_once_with("warning")
            logger.error.assert_called_once_with("error")
            logger.critical.assert_called_once_with("fatal")
            logger.debug.assert_not_called()

    def test_install_registers_the_canonical_handler(self):
        with patch.object(QtCore, "qInstallMessageHandler") as install:
            qt_log_handler.install_qt_message_handler()
        install.assert_called_once_with(qt_log_handler._qt_message_handler)
