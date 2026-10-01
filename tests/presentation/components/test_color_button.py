from shiboken6 import delete
from PySide6 import QtGui, QtWidgets
from ost_visualizer.presentation.components.color_button import ColorButton
from unittest.mock import patch
import unittest
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class ColorButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_programmatic_color_is_copied_and_does_not_emit(self):
        color = QtGui.QColor("#123456")
        button = ColorButton(color, show_color_tooltip=True)
        self.addCleanup(delete, button)
        changes = []
        button.colorChanged.connect(lambda: changes.append(button.color()))
        color.setRgb(255, 255, 255)
        self.assertEqual(button.color().name(), "#123456")
        replacement = QtGui.QColor("#abcdef")
        button.set_color(replacement)
        replacement.setRgb(1, 2, 3)
        returned = button.color()
        returned.setRgb(0, 0, 0)
        self.assertEqual(button.color().name(), "#abcdef")
        self.assertEqual(button.toolTip(), "#abcdef")
        center = button.icon().pixmap(24, 24).toImage().pixelColor(12, 12)
        self.assertEqual(center.name(), "#abcdef")
        self.assertEqual(changes, [])

    def test_acceptance_preserves_each_callers_notification_policy(self):
        for notify in (False, True):
            with self.subTest(notify_on_unchanged=notify):
                button = ColorButton(
                    QtGui.QColor("#123456"), notify_on_unchanged=notify
                )
                self.addCleanup(delete, button)
                changes = []
                button.colorChanged.connect(
                    lambda: changes.append(button.color().name())
                )
                with (
                    patch.object(
                        QtWidgets.QColorDialog,
                        "exec",
                        return_value=QtWidgets.QDialog.DialogCode.Accepted,
                    ),
                    patch.object(
                        QtWidgets.QColorDialog,
                        "currentColor",
                        return_value=QtGui.QColor("#123456"),
                    ),
                ):
                    button.click()
                self.assertEqual(changes, ["#123456"] if notify else [])
                changes.clear()
                with (
                    patch.object(
                        QtWidgets.QColorDialog,
                        "exec",
                        return_value=QtWidgets.QDialog.DialogCode.Accepted,
                    ),
                    patch.object(
                        QtWidgets.QColorDialog,
                        "currentColor",
                        return_value=QtGui.QColor("#abcdef"),
                    ),
                ):
                    button.click()
                self.assertEqual(changes, ["#abcdef"])
                self.assertEqual(button.color().name(), "#abcdef")
                self.assertEqual(button.toolTip(), "")

    def test_rejected_or_invalid_selection_keeps_color_and_does_not_emit(self):
        cases = (
            (
                "rejected",
                QtWidgets.QDialog.DialogCode.Rejected,
                QtGui.QColor("#abcdef"),
            ),
            ("invalid", QtWidgets.QDialog.DialogCode.Accepted, QtGui.QColor()),
        )
        for label, result, selected in cases:
            with self.subTest(case=label):
                button = ColorButton(
                    QtGui.QColor("#123456"),
                    show_color_tooltip=True,
                    notify_on_unchanged=True,
                )
                self.addCleanup(delete, button)
                changes = []
                button.colorChanged.connect(lambda: changes.append(1))
                with (
                    patch.object(QtWidgets.QColorDialog, "exec", return_value=result),
                    patch.object(
                        QtWidgets.QColorDialog,
                        "currentColor",
                        return_value=selected,
                    ),
                ):
                    button.click()
                self.assertEqual(changes, [])
                self.assertEqual(button.color().name(), "#123456")
                self.assertEqual(button.toolTip(), "#123456")


class ColorButtonConditionBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls._quit_on_last_window_closed = cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.setQuitOnLastWindowClosed(cls._quit_on_last_window_closed)

    def tearDown(self):
        self.app.processEvents()

    def test_condition_color_picker_stops_when_button_is_destroyed(self):
        button = ColorButton(QtGui.QColor(0, 0, 0), notify_on_unchanged=True)
        changes = []
        button.colorChanged.connect(lambda: changes.append(button.color()))

        class DestroyingColorDialog(QtWidgets.QColorDialog):
            def exec(self):
                delete(self.parent())
                return QtWidgets.QDialog.DialogCode.Accepted

            def currentColor(self):
                raise AssertionError("destroyed color dialog must not be read")

        with patch(
            "ost_visualizer.presentation.components.color_button.QtWidgets.QColorDialog",
            DestroyingColorDialog,
        ):
            button._choose_color()
        self.assertEqual(changes, [])

    def test_repeated_condition_color_picker_cancellation_releases_dialogs(self):
        button = ColorButton(QtGui.QColor(0, 0, 0), notify_on_unchanged=True)
        real_color_dialog = QtWidgets.QColorDialog
        try:
            with patch(
                "ost_visualizer.presentation.components.color_button.QtWidgets.QColorDialog",
                side_effect=lambda color, parent: real_color_dialog(color, parent),
            ), patch.object(
                real_color_dialog,
                "exec",
                return_value=QtWidgets.QDialog.DialogCode.Rejected,
            ) as exec_mock:
                for _ in range(100):
                    button._choose_color()
            self.assertEqual(exec_mock.call_count, 100)
            self.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
            self.app.processEvents()
            self.assertEqual(button.findChildren(real_color_dialog), [])
        finally:
            button.deleteLater()
