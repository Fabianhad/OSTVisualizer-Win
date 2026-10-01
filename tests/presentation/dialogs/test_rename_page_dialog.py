from shiboken6 import delete, isValid
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
            "navigate_same_name",
        ):
            with self.subTest(transition=transition):
                second_name = (
                    "Page A" if transition == "navigate_same_name" else "Page B"
                )
                dialog = RenamePageDialog(
                    None,
                    None,
                    [
                        PageRenameTarget("a", "Page A"),
                        PageRenameTarget("b", second_name),
                    ],
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
                    elif transition in ("navigate", "navigate_same_name"):
                        dialog._go_next()
                        self.assertEqual(dialog._current_page().uid, "b")
                    elif transition == "disabled":
                        dialog.set_interactive(False)
                    elif transition == "cleanup":
                        dialog.cleanup()
                    elif transition == "repeat_show":
                        dialog.showEvent(QtGui.QShowEvent())
                    if transition not in (
                        "current",
                        "repeat_show",
                        "destroy",
                        "navigate_same_name",
                    ):
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
                        if transition in ("current", "repeat_show"):
                            self.assertEqual(edit.selectedText(), "Page A")
                        if transition not in (
                            "current",
                            "repeat_show",
                            "destroy",
                            "navigate_same_name",
                        ):
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
        control = RenamePageDialog(
            None,
            None,
            [PageRenameTarget("page-1", "Page 1")],
            "page-1",
            lambda _uid, _name: True,
        )
        self.addCleanup(lambda: delete(control) if isValid(control) else None)
        control_calls = []
        control._select_new_name = lambda: control_calls.append(True)
        control.show()
        self.app.processEvents()
        self.assertEqual(control_calls, [True])

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
        self.assertEqual(len(callbacks), 1)
        delete(dialog)
        with patch(
            "ost_visualizer.presentation.dialogs.rename_page_dialog.show_warning"
        ) as show_warning:
            callbacks[0](True)
            callbacks[0](False)
        show_warning.assert_not_called()

    def test_rename_page_async_completion_accepts_or_warns_and_restores_controls(self):
        calls = []
        callbacks = []
        dialog = RenamePageDialog(
            None,
            None,
            [PageRenameTarget("page-1", "Page 1")],
            "page-1",
            lambda _uid, _name: self.fail("SQL must not use synchronous save"),
            save_async_fn=lambda uid, name, completed: calls.append((uid, name))
            or callbacks.append(completed)
            or True,
        )
        self.addCleanup(lambda: delete(dialog) if isValid(dialog) else None)
        dialog._new_name_edit.setText("Renamed")
        dialog._on_ok()
        self.assertEqual(calls, [("page-1", "Renamed")])
        self.assertFalse(dialog._ok_btn.isEnabled())
        self.assertFalse(dialog._new_name_edit.isEnabled())
        dialog.reject()
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
        with patch(
            "ost_visualizer.presentation.dialogs.rename_page_dialog.show_warning"
        ) as show_warning:
            callbacks[0](False)
        show_warning.assert_called_once_with(
            dialog, "Save Failed", "Failed to rename page."
        )
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
        self.assertTrue(dialog._ok_btn.isEnabled())
        self.assertTrue(dialog._new_name_edit.isEnabled())
        dialog._on_ok()
        self.assertEqual(calls, [("page-1", "Renamed"), ("page-1", "Renamed")])
        callbacks[1](True)
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
