import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from shiboken6 import delete
from ost_visualizer.domain.entities.version_info import VersionInfo
from ost_visualizer.presentation.dialogs.update_dialog import UpdateDialog


class UpdateDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_changelog_and_link_escape_remote_text_and_keep_section_order(self):
        info = VersionInfo(
            "2",
            "1",
            True,
            release_date="2026-09-30T12:00:00",
            release_url='https://example.invalid/?q="unsafe"',
            changelog={"fixed": ["<unsafe>"], "added": ["A & B"]},
        )
        dialog = UpdateDialog(Mock(), None, info)
        self.addCleanup(delete, dialog)
        content = dialog._build_changelog_html()
        self.assertLess(content.index("Added"), content.index("Fixed"))
        self.assertIn("A &amp; B", content)
        self.assertIn("&lt;unsafe&gt;", content)
        self.assertIn("&quot;unsafe&quot;", dialog._build_release_link().text())
        self.assertEqual(dialog._release_date_text(), " (2026-09-30)")

    def test_download_and_later_only_launch_browser_for_download(self):
        for choice, result in (("Yes, Download", 1), ("No, Later", 0)):
            with self.subTest(choice=choice):
                dialog = UpdateDialog(
                    Mock(),
                    None,
                    VersionInfo("2", "1", True, "https://example.invalid/download"),
                )
                self.addCleanup(delete, dialog)
                box = dialog.findChild(QtWidgets.QDialogButtonBox)
                with patch(
                    "ost_visualizer.presentation.dialogs.update_dialog.webbrowser.open"
                ) as browser:
                    next(
                        button for button in box.buttons() if button.text() == choice
                    ).click()
                    if result:
                        browser.assert_called_once_with(
                            "https://example.invalid/download"
                        )
                    else:
                        browser.assert_not_called()
                self.assertEqual(dialog.result(), result)
