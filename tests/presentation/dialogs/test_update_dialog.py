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
        self.assertEqual(
            dialog._build_changelog_html(),
            "<p><strong>Added</strong></p><ul><li>A &amp; B</li></ul>"
            "<p><strong>Fixed</strong></p><ul><li>&lt;unsafe&gt;</li></ul>",
        )
        self.assertEqual(
            dialog._build_release_link().text(),
            '<a href="https://example.invalid/?q=&quot;unsafe&quot;">'
            "View full release notes</a>",
        )
        self.assertEqual(dialog._release_date_text(), " (2026-09-30)")

    def test_release_link_falls_back_and_empty_remote_fields_are_omitted(self):
        info = VersionInfo(
            "2", "1", True, release_notes_url="https://example.invalid/notes"
        )
        dialog = UpdateDialog(Mock(), None, info)
        self.addCleanup(delete, dialog)
        self.assertEqual(
            dialog._build_release_link().text(),
            '<a href="https://example.invalid/notes">View full release notes</a>',
        )
        self.assertEqual(dialog._build_changelog_html(), "")
        self.assertIsNone(dialog._build_changelog_widget())
        self.assertEqual(dialog._release_date_text(), "")
        bare = UpdateDialog(Mock(), None, VersionInfo("2", "1", True))
        self.addCleanup(delete, bare)
        self.assertIsNone(bare._build_release_link())

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

    def test_download_without_url_accepts_without_launching_browser(self):
        dialog = UpdateDialog(Mock(), None, VersionInfo("2", "1", True))
        self.addCleanup(delete, dialog)
        box = dialog.findChild(QtWidgets.QDialogButtonBox)
        with patch(
            "ost_visualizer.presentation.dialogs.update_dialog.webbrowser.open"
        ) as browser, self.assertLogs(
            "ost_visualizer.presentation.dialogs.update_dialog", level="WARNING"
        ):
            next(
                button for button in box.buttons() if button.text() == "Yes, Download"
            ).click()
        browser.assert_not_called()
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
