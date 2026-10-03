import os
import unittest
from PySide6 import QtCore, QtGui, QtWidgets

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.utils.qt_lifecycle import (
    delete_later_if_valid,
    exec_transient_menu,
)
from shiboken6 import delete, isValid
from tests.presentation.utils.dialog_lifecycle_support import (
    _app as _dialog_lifecycle_support__app,
)


class ExecTransientMenuTests(unittest.TestCase):
    def test_repeated_transient_context_menus_return_to_owner_baseline(self):
        app = _dialog_lifecycle_support__app()
        owner = QtWidgets.QWidget()

        class ImmediateMenu(QtWidgets.QMenu):
            def exec(self, _global_pos):
                return None

        try:
            for _ in range(500):
                menu = ImmediateMenu(owner)
                menu.addAction("Action")
                exec_transient_menu(menu, QtCore.QPoint())
            app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
            app.processEvents()
            self.assertEqual(owner.findChildren(ImmediateMenu), [])
        finally:
            owner.deleteLater()

    def test_transient_menu_returns_chosen_action_and_is_still_released(self):
        app = _dialog_lifecycle_support__app()
        owner = QtWidgets.QWidget()
        chosen = QtGui.QAction("Chosen", owner)

        class ChoosingMenu(QtWidgets.QMenu):
            def exec(self, global_pos):
                self.position = global_pos
                return chosen

        try:
            menu = ChoosingMenu(owner)
            result = exec_transient_menu(menu, QtCore.QPoint(3, 4))
            self.assertIs(result, chosen)
            self.assertEqual(menu.position, QtCore.QPoint(3, 4))
            app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
            self.assertEqual(owner.findChildren(ChoosingMenu), [])
        finally:
            owner.deleteLater()

    def test_transient_menu_is_released_when_exec_raises(self):
        app = _dialog_lifecycle_support__app()
        owner = QtWidgets.QWidget()

        class FailingMenu(QtWidgets.QMenu):
            def exec(self, _global_pos):
                raise RuntimeError("menu failed")

        try:
            menu = FailingMenu(owner)
            with self.assertRaises(RuntimeError):
                exec_transient_menu(menu, QtCore.QPoint())
            app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
            self.assertEqual(owner.findChildren(FailingMenu), [])
        finally:
            owner.deleteLater()


class DeleteLaterIfValidTests(unittest.TestCase):
    def test_already_deleted_object_is_tolerated(self):
        _dialog_lifecycle_support__app()
        widget = QtWidgets.QWidget()
        delete(widget)
        self.assertFalse(isValid(widget))
        delete_later_if_valid(widget)

    def test_runtime_error_from_a_still_valid_object_is_not_hidden(self):
        class Failing:
            def deleteLater(self):
                raise RuntimeError("unrelated failure")

        self.assertTrue(isValid(Failing()))
        with self.assertRaisesRegex(RuntimeError, "unrelated failure"):
            delete_later_if_valid(Failing())

    def test_valid_object_is_scheduled_for_deletion(self):
        app = _dialog_lifecycle_support__app()
        widget = QtWidgets.QWidget()
        delete_later_if_valid(widget)
        self.assertTrue(isValid(widget))
        app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        self.assertFalse(isValid(widget))
