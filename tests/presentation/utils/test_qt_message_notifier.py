import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.utils.qt_message_notifier import QtMessageNotifier
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete, isValid
from tests.presentation.utils.dialog_lifecycle_support import (
    _app as _dialog_lifecycle_support__app,
)


class DialogLifecycleTests(unittest.TestCase):
    def test_message_notifier_cleanup_tolerates_parent_destroyed_dialog(self):
        _dialog_lifecycle_support__app()
        parent = QtWidgets.QDialog()
        parent.show()
        notifier = QtMessageNotifier(parent=None)
        notifier.set_parent(parent)
        notifier.post_message("Notice", "Queued work completed")
        self.assertIsNotNone(notifier._current_dialog)
        delete(parent)
        notifier.cleanup()
        self.assertIsNone(notifier._current_dialog)
        self.assertIsNone(notifier._default_parent)

    def test_message_notifier_drops_stale_queue_after_parent_is_destroyed(self):
        _dialog_lifecycle_support__app()
        parent = QtWidgets.QDialog()
        notifier = QtMessageNotifier(parent=None)
        notifier.set_parent(parent)
        notifier._update_active = True
        notifier.post_message("Notice", "Queued work completed")
        self.assertEqual(len(notifier._queue), 1)
        delete(parent)
        notifier._update_active = False
        notifier._maybe_show_next()
        self.assertEqual(notifier._queue, [])
        self.assertIsNone(notifier._current_dialog)
        self.assertIsNone(notifier._default_parent)
        notifier.cleanup()

    def test_messages_are_shown_one_at_a_time_in_order_with_severity_icons(self):
        app = _dialog_lifecycle_support__app()
        parent = QtWidgets.QDialog()
        parent.show()
        notifier = QtMessageNotifier(parent=None)
        notifier.set_parent(parent)
        try:
            notifier.post_message("First", "one", "error")
            notifier.post_message("Second", "two", "unknown")
            notifier.post_message("Third", "three", "warning")
            first = notifier._current_dialog
            self.assertEqual(first.windowTitle(), "First")
            self.assertEqual(first.text(), "one")
            self.assertEqual(first.icon(), QtWidgets.QMessageBox.Icon.Critical)
            self.assertEqual([item[0] for item in notifier._queue], ["Second", "Third"])
            first.done(0)
            second = notifier._current_dialog
            self.assertIsNot(second, first)
            self.assertEqual(second.windowTitle(), "Second")
            self.assertEqual(second.icon(), QtWidgets.QMessageBox.Icon.Information)
            self.assertEqual([item[0] for item in notifier._queue], ["Third"])
            second.done(0)
            third = notifier._current_dialog
            self.assertEqual(third.windowTitle(), "Third")
            self.assertEqual(third.icon(), QtWidgets.QMessageBox.Icon.Warning)
            self.assertEqual(notifier._queue, [])
            third.done(0)
            self.assertIsNone(notifier._current_dialog)
            app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
            self.assertEqual(parent.findChildren(QtWidgets.QMessageBox), [])
        finally:
            notifier.cleanup()
            parent.deleteLater()

    def test_messages_wait_while_update_is_active_and_flush_afterwards(self):
        _dialog_lifecycle_support__app()
        parent = QtWidgets.QDialog()
        parent.show()
        notifier = QtMessageNotifier(parent=None)
        notifier.set_parent(parent)
        try:
            notifier.set_update_active(True)
            notifier.post_message("Held", "waiting")
            self.assertIsNone(notifier._current_dialog)
            self.assertEqual(len(notifier._queue), 1)
            notifier.set_update_active(False)
            self.assertEqual(notifier._current_dialog.windowTitle(), "Held")
            self.assertEqual(notifier._queue, [])
        finally:
            notifier.cleanup()
            parent.deleteLater()

    def test_messages_wait_for_hidden_parent_without_showing_dialog(self):
        _dialog_lifecycle_support__app()
        parent = QtWidgets.QDialog()
        notifier = QtMessageNotifier(parent=None)
        notifier.set_parent(parent)
        retries = []
        try:
            with patch.object(
                QtCore.QTimer, "singleShot", lambda delay, fn: retries.append(delay)
            ):
                notifier.post_message("Hidden", "later")
            self.assertEqual(retries, [100])
            self.assertIsNone(notifier._current_dialog)
            self.assertEqual(len(notifier._queue), 1)
        finally:
            notifier.cleanup()
            parent.deleteLater()

    def test_cleanup_releases_live_dialog_queue_and_stops_further_messages(self):
        app = _dialog_lifecycle_support__app()
        parent = QtWidgets.QDialog()
        parent.show()
        notifier = QtMessageNotifier(parent=None)
        notifier.set_parent(parent)
        try:
            notifier.post_message("Open", "shown")
            notifier.post_message("Queued", "waiting")
            dialog = notifier._current_dialog
            self.assertEqual(len(notifier._queue), 1)
            notifier.cleanup()
            self.assertIsNone(notifier._current_dialog)
            self.assertEqual(notifier._queue, [])
            self.assertIsNone(notifier._default_parent)
            app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
            self.assertFalse(isValid(dialog))
            notifier.post_message("After", "ignored")
            self.assertEqual(notifier._queue, [])
            self.assertIsNone(notifier._current_dialog)
        finally:
            parent.deleteLater()
