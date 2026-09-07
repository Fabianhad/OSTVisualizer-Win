import unittest
from unittest.mock import patch
from PySide6 import QtGui, QtWidgets
from shiboken6 import delete
from ost_visualizer.presentation.dialogs.rename_page_dialog import (
    RenamePageDialog,
    PageRenameTarget,
)


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
