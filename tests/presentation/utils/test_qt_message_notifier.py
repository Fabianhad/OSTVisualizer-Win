import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.utils.qt_message_notifier import QtMessageNotifier
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete
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
