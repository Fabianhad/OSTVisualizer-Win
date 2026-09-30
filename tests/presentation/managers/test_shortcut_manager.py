import unittest
from ost_visualizer.presentation.managers.shortcut_manager import ShortcutManager
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest


class ShortcutWindowOwnershipTests(unittest.TestCase):
    @staticmethod
    def _app():
        return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_window_shortcuts_follow_active_detached_window(self):
        app = self._app()
        main = QtWidgets.QMainWindow()
        main_target = QtWidgets.QPushButton(main)
        main.setCentralWidget(main_target)
        main_calls = []
        main_action = QtGui.QAction("Main Undo", main)
        ShortcutManager.apply_to_action(main_action, "undo")
        main_action.triggered.connect(lambda: main_calls.append(True))
        main.addAction(main_action)
        detached = QtWidgets.QMainWindow(main)
        detached.setWindowFlags(QtCore.Qt.WindowType.Window)
        detached_target = QtWidgets.QPushButton(detached)
        detached.setCentralWidget(detached_target)
        detached_calls = []
        ShortcutManager.register_shortcut(
            detached,
            "undo",
            lambda: detached_calls.append(True),
        )
        self.addCleanup(app.processEvents)
        self.addCleanup(main.close)
        self.addCleanup(detached.close)
        main.show()
        detached.show()
        detached.activateWindow()
        detached_target.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        app.processEvents()
        QTest.keyClick(
            detached_target,
            QtCore.Qt.Key.Key_Z,
            QtCore.Qt.KeyboardModifier.ControlModifier,
        )
        QTest.keyRelease(detached_target, QtCore.Qt.Key.Key_Control)
        app.processEvents()
        self.assertEqual(detached_calls, [True])
        self.assertEqual(main_calls, [])
        main.activateWindow()
        main_target.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        app.processEvents()
        QTest.keyClick(
            main_target,
            QtCore.Qt.Key.Key_Z,
            QtCore.Qt.KeyboardModifier.ControlModifier,
        )
        QTest.keyRelease(main_target, QtCore.Qt.Key.Key_Control)
        app.processEvents()
        self.assertEqual(detached_calls, [True])
        self.assertEqual(main_calls, [True])

    def test_detached_editable_control_keeps_native_undo(self):
        app = self._app()
        detached = QtWidgets.QMainWindow()
        editor = QtWidgets.QLineEdit(detached)
        detached.setCentralWidget(editor)
        shortcut_calls = []
        ShortcutManager.register_shortcut(
            detached,
            "undo",
            lambda: shortcut_calls.append(True),
        )
        self.addCleanup(app.processEvents)
        self.addCleanup(detached.close)
        detached.show()
        detached.activateWindow()
        editor.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        editor.setText("before")
        editor.selectAll()
        QTest.keyClicks(editor, "after")
        app.processEvents()
        QTest.keyClick(
            editor,
            QtCore.Qt.Key.Key_Z,
            QtCore.Qt.KeyboardModifier.ControlModifier,
        )
        QTest.keyRelease(editor, QtCore.Qt.Key.Key_Control)
        app.processEvents()
        self.assertEqual(editor.text(), "before")
        self.assertEqual(shortcut_calls, [])
