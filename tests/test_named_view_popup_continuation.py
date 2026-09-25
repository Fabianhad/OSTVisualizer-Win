import unittest
from unittest.mock import patch
from ost_visualizer.presentation.dialogs.select_named_view_dialog import (
    SelectNamedViewDialog,
)
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete


class NamedViewPopupContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_queued_popup_obeys_dialog_lifetime_and_coalesces_requests(self):
        for transition in ("current", "close", "reopen", "disabled", "destroy"):
            with self.subTest(transition=transition):
                dialog = SelectNamedViewDialog([("v", "p", "Page", "Lobby")])
                dialog.show()
                self.app.processEvents()
                completer = dialog._named_view_combo.completer()
                completer.popup().hide()
                with patch.object(
                    completer, "complete", wraps=completer.complete
                ) as complete:
                    dialog._queue_show_current_completions()
                    dialog._queue_show_current_completions()
                    if transition in ("close", "reopen"):
                        dialog.reject()
                        if transition == "reopen":
                            dialog.show()
                    elif transition == "disabled":
                        dialog._named_view_combo.setEnabled(False)
                    elif transition == "destroy":
                        delete(dialog)
                    try:
                        self.app.processEvents()
                        self.assertEqual(
                            complete.call_count, 1 if transition == "current" else 0
                        )
                        if transition != "destroy":
                            self.assertEqual(
                                completer.popup().isVisible(), transition == "current"
                            )
                    finally:
                        if transition != "destroy":
                            completer.popup().hide()
                            delete(dialog)
                        QtCore.QCoreApplication.sendPostedEvents(
                            None, QtCore.QEvent.Type.DeferredDelete
                        )
