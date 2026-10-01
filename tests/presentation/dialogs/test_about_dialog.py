import os
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from shiboken6 import delete
from ost_visualizer.application.interfaces.i_window_icon_provider import (
    IWindowIconProvider,
)
from ost_visualizer.application.services.update_check_service import UpdateCheckService
from ost_visualizer.presentation.dialogs.about_dialog import AboutDialog


class AboutDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_content_close_button_and_repeated_cleanup(self):
        icon_provider = Mock(spec=IWindowIconProvider)
        dialog = AboutDialog(icon_provider, creator_name="Test Creator")
        self.addCleanup(delete, dialog)
        icon_provider.set_window_icon.assert_called_once_with(dialog)
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
        self.assertIn("Test Creator", dialog.content_view.toPlainText())
        self.assertIn(
            UpdateCheckService.CURRENT_VERSION, dialog.content_view.toPlainText()
        )
        dialog.close_button.click()
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        dialog.cleanup()
        dialog.cleanup()
        self.assertIsNone(dialog.content_view)
        self.assertIsNone(dialog.close_button)
        self.assertIsNone(dialog.creator_name)
        self.assertIsNone(dialog.icon_provider)
