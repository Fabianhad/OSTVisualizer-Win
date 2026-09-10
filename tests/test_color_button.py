import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtGui, QtWidgets
from shiboken6 import delete
from ost_visualizer.presentation.components.color_button import ColorButton


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
        color.setNamedColor("#ffffff")
        self.assertEqual(button.color().name(), "#123456")
        button.set_color(QtGui.QColor("#abcdef"))
        returned = button.color()
        returned.setNamedColor("#000000")
        self.assertEqual(button.color().name(), "#abcdef")
        self.assertEqual(button.toolTip(), "#abcdef")
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
