import unittest
from unittest.mock import patch
from ost_visualizer.presentation.utils.compact_context_menu import (
    populate_compact_context_menu,
)
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete


class CompactMenuContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_queued_overflow_requires_current_visible_menu_page(self):
        for transition in ("current", "replace", "close", "destroy"):
            with self.subTest(transition=transition):
                menu = QtWidgets.QMenu()
                callbacks = []

                def add(target, value):
                    return target.addAction(str(value))

                populate_compact_context_menu(menu, list(range(40)), add)
                menu.show()
                initial = [a.text() for a in menu.actions()]
                overflow = menu.actions()[-1].defaultWidget()
                with patch.object(
                    QtCore.QTimer, "singleShot", lambda delay, fn: callbacks.append(fn)
                ):
                    overflow.click()
                if transition == "replace":
                    populate_compact_context_menu(menu, ["New target"], add)
                elif transition == "close":
                    menu.close()
                elif transition == "destroy":
                    delete(menu)
                try:
                    callbacks[0]()
                    if transition == "destroy":
                        continue
                    labels = [a.text() for a in menu.actions()]
                    if transition == "current":
                        self.assertNotEqual(labels, initial)
                        self.assertIn("39", labels)
                    elif transition == "replace":
                        self.assertEqual(labels, ["New target"])
                    else:
                        self.assertEqual(labels, initial)
                finally:
                    if transition != "destroy":
                        delete(menu)
                    QtCore.QCoreApplication.sendPostedEvents(
                        None, QtCore.QEvent.Type.DeferredDelete
                    )
