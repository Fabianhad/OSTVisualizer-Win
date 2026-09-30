import os
import unittest
from PySide6 import QtCore, QtWidgets

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.utils.qt_lifecycle import exec_transient_menu
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
