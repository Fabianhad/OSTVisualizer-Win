import unittest
from ost_visualizer.presentation.actions.action_ids import (
    ACTION_COPY,
    ACTION_DELETE,
    ACTION_PASTE,
    ACTION_REDO,
    ACTION_UNDO,
)
from ost_visualizer.presentation.managers.shortcut_manager import (
    ShortcutId,
    ShortcutManager,
)
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


class ShortcutRegistryTests(unittest.TestCase):
    @staticmethod
    def _app():
        return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_spec_resolves_ids_and_action_keys_to_the_same_sequence(self):
        self.assertEqual(ShortcutManager.spec(ShortcutId.UNDO).sequence, "Ctrl+Z")
        self.assertEqual(ShortcutManager.spec(ACTION_UNDO).sequence, "Ctrl+Z")
        self.assertEqual(ShortcutManager.spec(ACTION_REDO).sequence, "Ctrl+Y")
        self.assertEqual(ShortcutManager.spec(ACTION_DELETE).sequence, "Del")
        self.assertIsNone(ShortcutManager.spec("not_a_shortcut"))
        self.assertEqual(
            ShortcutManager.sequence(ACTION_UNDO),
            QtGui.QKeySequence("Ctrl+Z"),
        )
        self.assertTrue(ShortcutManager.sequence("not_a_shortcut").isEmpty())

    def test_every_shortcut_id_has_a_unique_sequence(self):
        sequences = [
            ShortcutManager.spec(shortcut_id).sequence for shortcut_id in ShortcutId
        ]
        self.assertEqual(len(sequences), len(ShortcutId))
        self.assertEqual(len(set(sequences)), len(sequences))
        for shortcut_id in ShortcutId:
            with self.subTest(shortcut_id=shortcut_id):
                self.assertFalse(ShortcutManager.sequence(shortcut_id).isEmpty())

    def test_apply_to_action_sets_sequence_and_leaves_unknown_actions_untouched(self):
        self._app()
        action = QtGui.QAction("Redo")
        ShortcutManager.apply_to_action(action, ACTION_REDO)
        self.assertEqual(action.shortcut(), QtGui.QKeySequence("Ctrl+Y"))
        unknown = QtGui.QAction("Unknown")
        ShortcutManager.apply_to_action(unknown, "not_a_shortcut")
        self.assertTrue(unknown.shortcut().isEmpty())

    def test_register_shortcut_rejects_unknown_shortcut(self):
        self._app()
        parent = QtWidgets.QWidget()
        self.addCleanup(parent.deleteLater)
        with self.assertRaisesRegex(ValueError, "Unknown shortcut: not_a_shortcut"):
            ShortcutManager.register_shortcut(parent, "not_a_shortcut", lambda: None)
        self.assertEqual(parent.findChildren(QtGui.QShortcut), [])

    def test_registered_shortcut_uses_window_context_and_sequence(self):
        self._app()
        parent = QtWidgets.QWidget()
        self.addCleanup(parent.deleteLater)
        shortcut = ShortcutManager.register_shortcut(parent, ACTION_COPY, lambda: None)
        self.assertEqual(shortcut.key(), QtGui.QKeySequence("Ctrl+C"))
        self.assertEqual(shortcut.context(), QtCore.Qt.ShortcutContext.WindowShortcut)
        self.assertIs(shortcut.parent(), parent)

    def test_text_input_guard_applies_only_when_requested_and_focus_is_editable(self):
        app = self._app()
        window = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(window)
        editor = QtWidgets.QLineEdit()
        button = QtWidgets.QPushButton("Action")
        layout.addWidget(editor)
        layout.addWidget(button)
        self.addCleanup(app.processEvents)
        self.addCleanup(window.close)
        guarded_calls = []
        unguarded_calls = []
        guarded = ShortcutManager.register_shortcut(
            window,
            ACTION_COPY,
            lambda: guarded_calls.append(True),
            ignore_when_text_input=True,
        )
        unguarded = ShortcutManager.register_shortcut(
            window,
            ACTION_PASTE,
            lambda: unguarded_calls.append(True),
        )
        window.show()
        window.activateWindow()
        editor.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        app.processEvents()
        self.assertIs(QtWidgets.QApplication.focusWidget(), editor)
        guarded.activated.emit()
        unguarded.activated.emit()
        self.assertEqual((guarded_calls, unguarded_calls), ([], [True]))
        button.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        app.processEvents()
        self.assertIs(QtWidgets.QApplication.focusWidget(), button)
        guarded.activated.emit()
        self.assertEqual(guarded_calls, [True])

    def test_text_editing_widget_classification(self):
        self._app()
        self.assertFalse(ShortcutManager.is_text_editing_widget(None))
        self.assertFalse(
            ShortcutManager.should_ignore_for_text_input(QtWidgets.QPushButton())
        )
        for widget_type in (
            QtWidgets.QLineEdit,
            QtWidgets.QTextEdit,
            QtWidgets.QPlainTextEdit,
            QtWidgets.QSpinBox,
            QtWidgets.QDoubleSpinBox,
        ):
            with self.subTest(widget_type=widget_type.__name__):
                self.assertTrue(ShortcutManager.is_text_editing_widget(widget_type()))
        combo = QtWidgets.QComboBox()
        self.assertFalse(ShortcutManager.is_text_editing_widget(combo))
        combo.setEditable(True)
        self.assertTrue(ShortcutManager.is_text_editing_widget(combo))
        self.assertTrue(ShortcutManager.should_ignore_for_text_input(combo))
