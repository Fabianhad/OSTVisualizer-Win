import unittest
from types import SimpleNamespace
from unittest.mock import call, patch
from PySide6 import QtCore
from ost_visualizer.presentation.utils import qt_log_handler

SCREEN = SimpleNamespace(category="qt.qpa.screen")


def unreadable_monitor_message(display, error="Unknown error 0xe0000225."):
    return f'"Unable to open monitor interface to {display}:" "{error}"'


class UnreadableMonitorWarningTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(qt_log_handler, "_unreadable_monitor_displays", set())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_warning_is_dropped_and_logged_once_per_display_at_debug(self):
        with self.assertLogs("ost_visualizer.qt", level="DEBUG") as logs:
            for display in ("\\\\.\\DISPLAY2", "\\\\.\\DISPLAY2", "\\\\.\\DISPLAY3"):
                qt_log_handler._qt_message_handler(
                    QtCore.QtMsgType.QtWarningMsg,
                    SCREEN,
                    unreadable_monitor_message(display),
                )
        self.assertEqual(
            [(record.levelname, record.getMessage()) for record in logs.records],
            [
                (
                    "DEBUG",
                    "Qt could not read the EDID of monitor \\\\.\\DISPLAY2 "
                    "(qt.qpa.screen, SetupAPI 0xe0000225); "
                    "Qt keeps its fallback screen metrics",
                ),
                (
                    "DEBUG",
                    "Qt could not read the EDID of monitor \\\\.\\DISPLAY3 "
                    "(qt.qpa.screen, SetupAPI 0xe0000225); "
                    "Qt keeps its fallback screen metrics",
                ),
            ],
        )

    def test_similar_messages_still_pass_through_with_their_severity(self):
        exact = unreadable_monitor_message("\\\\.\\DISPLAY2")
        other_category = SimpleNamespace(category="default")
        other_error = unreadable_monitor_message(
            "\\\\.\\DISPLAY2", "Unknown error 0xe000020b."
        )
        other_screen_warning = '"Unable to obtain handle for monitor"'
        with patch.object(qt_log_handler, "_qt_logger") as logger:
            qt_log_handler._qt_message_handler(
                QtCore.QtMsgType.QtWarningMsg, other_category, exact
            )
            qt_log_handler._qt_message_handler(
                QtCore.QtMsgType.QtWarningMsg, None, exact
            )
            qt_log_handler._qt_message_handler(
                QtCore.QtMsgType.QtWarningMsg, SCREEN, other_error
            )
            qt_log_handler._qt_message_handler(
                QtCore.QtMsgType.QtWarningMsg, SCREEN, other_screen_warning
            )
            qt_log_handler._qt_message_handler(
                QtCore.QtMsgType.QtWarningMsg, SCREEN, f"prefix {exact}"
            )
            qt_log_handler._qt_message_handler(
                QtCore.QtMsgType.QtCriticalMsg, SCREEN, exact
            )
        self.assertEqual(
            logger.mock_calls,
            [
                call.warning(exact),
                call.warning(exact),
                call.warning(other_error),
                call.warning(other_screen_warning),
                call.warning(f"prefix {exact}"),
                call.error(exact),
            ],
        )
        self.assertEqual(qt_log_handler._unreadable_monitor_displays, set())

    def test_real_categorized_qt_warning_is_filtered_by_the_installed_handler(self):
        category = QtCore.QLoggingCategory("qt.qpa.screen")
        previous = QtCore.qInstallMessageHandler(qt_log_handler._qt_message_handler)
        self.addCleanup(QtCore.qInstallMessageHandler, previous)
        with self.assertLogs("ost_visualizer.qt", level="DEBUG") as logs:
            QtCore.qCWarning(category, unreadable_monitor_message("\\\\.\\DISPLAY2"))
            QtCore.qCWarning(category, '"Unable to obtain handle for monitor"')
        self.assertEqual(
            [record.levelname for record in logs.records], ["DEBUG", "WARNING"]
        )
        self.assertIn("\\\\.\\DISPLAY2", logs.records[0].getMessage())
        self.assertEqual(
            logs.records[1].getMessage(), '"Unable to obtain handle for monitor"'
        )


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
