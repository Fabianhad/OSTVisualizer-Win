import os
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete
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
        dialog = CreateDatabaseDialog(Mock(), parent)
        button = dialog.findChild(QtWidgets.QPushButton)
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
        self.assertEqual(
            button.cursor().shape(), QtCore.Qt.CursorShape.PointingHandCursor
        )
        self.assertEqual(parent.cursor().shape(), QtCore.Qt.CursorShape.ArrowCursor)
        button.click()
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
