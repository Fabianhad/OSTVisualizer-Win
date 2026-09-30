from shiboken6 import delete
from PySide6 import QtGui, QtWidgets
from ost_visualizer.presentation.dialogs.rename_page_dialog import (
    PageRenameTarget,
    RenamePageDialog,
)
from unittest.mock import patch
import unittest
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class RenamePageFocusContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_queued_initial_selection_does_not_override_newer_state(self):
        for transition in (
            "current",
            "hide",
            "close",
            "reopen",
            "edit",
            "navigate",
            "disabled",
            "destroy",
            "repeat_show",
            "cleanup",
        ):
            with self.subTest(transition=transition):
                dialog = RenamePageDialog(
                    None,
                    None,
                    [PageRenameTarget("a", "Page A"), PageRenameTarget("b", "Page B")],
                    "a",
                    lambda uid, name: True,
                )
                edit = dialog._new_name_edit
                with patch.object(
                    dialog, "_select_new_name", wraps=dialog._select_new_name
                ) as select:
                    dialog.show()
                    if transition == "hide":
                        dialog.hide()
                    elif transition == "close":
                        dialog.reject()
                    elif transition == "reopen":
                        dialog.hide()
                        dialog.show()
                    elif transition == "navigate":
                        dialog._go_next()
                    elif transition == "disabled":
                        dialog.set_interactive(False)
                    elif transition == "cleanup":
                        dialog.cleanup()
                    elif transition == "repeat_show":
                        dialog.showEvent(QtGui.QShowEvent())
                    if transition not in ("current", "repeat_show", "destroy"):
                        edit.setText("New draft")
                        edit.setSelection(1, 2)
                    if transition == "destroy":
                        delete(dialog)
                        dialog.cleanup()
                    select.reset_mock()
                    try:
                        self.app.processEvents()
                        self.assertEqual(
                            select.call_count,
                            1 if transition in ("current", "repeat_show") else 0,
                        )
                        if transition not in ("current", "repeat_show", "destroy"):
                            self.assertEqual(edit.selectedText(), "ew")
                    finally:
                        if transition != "destroy":
                            delete(dialog)


class RenamePageDialogAsyncLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_rename_page_focus_timer_is_dropped_after_dialog_destruction(self):
        dialog = RenamePageDialog(
            None,
            None,
            [PageRenameTarget("page-1", "Page 1")],
            "page-1",
            lambda _uid, _name: True,
        )
        calls = []
        dialog._select_new_name = lambda: calls.append(True)
        dialog.show()
        delete(dialog)
        self.app.processEvents()
        self.assertEqual(calls, [])

    def test_rename_page_completion_is_dropped_after_dialog_destruction(self):
        callbacks = []
        dialog = RenamePageDialog(
            None,
            None,
            [PageRenameTarget("page-1", "Page 1")],
            "page-1",
            lambda _uid, _name: self.fail("SQL must not use synchronous save"),
            save_async_fn=lambda _uid, _name, completed: callbacks.append(completed)
            or True,
        )
        dialog._new_name_edit.setText("Renamed")
        dialog._on_ok()
        delete(dialog)
        callbacks[0](True)
