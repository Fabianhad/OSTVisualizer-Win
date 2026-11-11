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


class AboutDialogCreditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_crane_model_and_gltf_loader_are_credited(self):
        dialog = AboutDialog(Mock(spec=IWindowIconProvider), creator_name="Creator")
        self.addCleanup(delete, dialog)
        text = " ".join(dialog.content_view.toPlainText().split())
        self.assertIn("\u201cTower Crane\u201d by Chamod on Sketchfab", text)
        self.assertIn("CC BY 4.0", text)
        self.assertIn("Modified: cut into reusable parts,", text)
        self.assertIn("ropes removed (ropes are generated)", text)
        self.assertIn("cgltf", text)
        # Every shipped model is credited, from its own kit.
        self.assertIn("“Liebherr tower crane” by Cem Alagozlu on Sketchfab", text)
        self.assertIn("jib side diagonals made one per bay", text)
        self.assertEqual(text.count("licensed under CC BY 4.0"), 2)
        html = dialog.content_view.toHtml()
        self.assertIn("https://creativecommons.org/licenses/by/4.0/", html)
        self.assertIn("tower-crane-49851dc7a51b43bda6aea06856c26a85", html)
        self.assertIn("liebherr-tower-crane-0f8befc223734608a5d54aad4904951f", html)
        self.assertIn("https://sketchfab.com/cem.alagozlu", html)
        dialog.cleanup()
