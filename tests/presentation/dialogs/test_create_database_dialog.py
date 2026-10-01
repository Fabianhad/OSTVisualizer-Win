import os
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete
from ost_visualizer.application.interfaces.i_window_icon_provider import (
    IWindowIconProvider,
)
from ost_visualizer.presentation.dialogs.create_database_dialog import (
    CreateDatabaseDialog,
)


class CreateDatabaseDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_creation_requires_explicit_acceptance_and_cursor_is_button_owned(self):
        parent = QtWidgets.QWidget()
        self.addCleanup(delete, parent)
        icon_provider = Mock(spec=IWindowIconProvider)
        dialog = CreateDatabaseDialog(icon_provider, parent)
        icon_provider.set_window_icon.assert_called_once_with(dialog)
        button = dialog.findChild(QtWidgets.QPushButton)
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
        self.assertEqual(
            button.cursor().shape(), QtCore.Qt.CursorShape.PointingHandCursor
        )
        self.assertEqual(parent.cursor().shape(), QtCore.Qt.CursorShape.ArrowCursor)
        button.click()
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
