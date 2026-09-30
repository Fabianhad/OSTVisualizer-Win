import os
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from shiboken6 import delete
from ost_visualizer.application.dtos.conflict_resolution_dtos import (
    ConflictResolutionAction,
)
from ost_visualizer.presentation.dialogs.synchronization_conflict_dialog import (
    SynchronizationConflictDialog,
)


class SynchronizationConflictDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_each_button_keeps_its_own_captured_resolution_action(self):
        labels = {
            "Reload": ConflictResolutionAction.RELOAD,
            "Discard Draft": ConflictResolutionAction.DISCARD_DRAFT,
            "Cancel": ConflictResolutionAction.CANCEL_READ_ONLY,
        }
        for label, expected in labels.items():
            with self.subTest(label=label):
                dialog = SynchronizationConflictDialog(
                    Mock(), "Conflict", tuple(labels.values())
                )
                self.addCleanup(delete, dialog)
                box = dialog.findChild(QtWidgets.QDialogButtonBox)
                next(
                    button for button in box.buttons() if button.text() == label
                ).click()
                self.assertEqual(dialog.selected_action(), expected)
                self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)

    def test_window_rejection_does_not_select_reload(self):
        dialog = SynchronizationConflictDialog(
            Mock(), "Conflict", (ConflictResolutionAction.RELOAD,)
        )
        self.addCleanup(delete, dialog)
        dialog.reject()
        self.assertEqual(
            dialog.selected_action(), ConflictResolutionAction.CANCEL_READ_ONLY
        )
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
