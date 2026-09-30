import os
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from shiboken6 import delete
from ost_visualizer.application.services.update_check_service import UpdateCheckService
from ost_visualizer.presentation.dialogs.about_dialog import AboutDialog


class AboutDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_content_close_button_and_repeated_cleanup(self):
        dialog = AboutDialog(Mock(), creator_name="Test Creator")
        self.addCleanup(delete, dialog)
        self.assertIn("Test Creator", dialog.content_view.toPlainText())
        self.assertIn(
            UpdateCheckService.CURRENT_VERSION, dialog.content_view.toPlainText()
        )
        dialog.close_button.click()
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        dialog.cleanup()
        dialog.cleanup()
        self.assertIsNone(dialog.content_view)
        self.assertIsNone(dialog.icon_provider)
