import unittest
from unittest.mock import call, patch
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
            qt_log_handler._qt_message_handler(QtCore.QtMsgType.QtInfoMsg, None, "info")
            logger.warning.assert_called_once_with("warning")
            logger.error.assert_called_once_with("error")
            logger.critical.assert_called_once_with("fatal")
            logger.debug.assert_not_called()
            self.assertEqual(
                logger.mock_calls,
                [call.warning("warning"), call.error("error"), call.critical("fatal")],
            )

    def test_message_objects_are_logged_as_text(self):
        with patch.object(qt_log_handler, "_qt_logger") as logger:
            qt_log_handler._qt_message_handler(QtCore.QtMsgType.QtWarningMsg, None, 42)
        logger.warning.assert_called_once_with("42")

    def test_handler_logs_through_the_qt_logger_name(self):
        self.assertEqual(qt_log_handler._qt_logger.name, "ost_visualizer.qt")
        with self.assertLogs("ost_visualizer.qt", level="WARNING") as logs:
            qt_log_handler._qt_message_handler(
                QtCore.QtMsgType.QtCriticalMsg, None, "boom"
            )
        self.assertEqual(logs.output, ["ERROR:ost_visualizer.qt:boom"])

    def test_install_registers_the_canonical_handler(self):
        with patch.object(QtCore, "qInstallMessageHandler") as install:
            qt_log_handler.install_qt_message_handler()
        install.assert_called_once_with(qt_log_handler._qt_message_handler)
