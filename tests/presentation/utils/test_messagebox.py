import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.utils.messagebox import confirm_delete_conditions
from PySide6 import QtCore, QtWidgets
from tests.presentation.utils.dialog_lifecycle_support import (
    _app as _dialog_lifecycle_support__app,
)


class DialogLifecycleTests(unittest.TestCase):
    def test_repeated_condition_delete_prompts_release_message_boxes(self):
        app = _dialog_lifecycle_support__app()
        owner = QtWidgets.QWidget()
        try:
            with patch.object(
                QtWidgets.QMessageBox, "exec", return_value=0
            ), patch.object(QtWidgets.QMessageBox, "clickedButton", return_value=None):
                for index in range(100):
                    self.assertEqual(
                        confirm_delete_conditions(
                            owner, [(str(index), f"Condition {index}")]
                        ),
                        [],
                    )
            app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
            app.processEvents()
            self.assertEqual(owner.findChildren(QtWidgets.QMessageBox), [])
        finally:
            owner.deleteLater()
