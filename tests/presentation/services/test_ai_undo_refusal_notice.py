import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.services.ai_undo_refusal_notice import (
    DISCARD_BUTTON_TEXT,
    DISCARD_FAILED_TEXT,
    UNDO_REFUSED_TITLE,
    AiUndoRefusalNotice,
)
from PySide6 import QtCore, QtWidgets
from shiboken6 import isValid


class AiUndoRefusalNoticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.notice = AiUndoRefusalNotice()
        self.addCleanup(self.notice.cleanup)
        self.discards = []
        self.discard_result = True

    def discard(self):
        self.discards.append(True)
        return self.discard_result

    def discard_button(self, box):
        (button,) = [
            button
            for button in box.buttons()
            if box.buttonRole(button) == QtWidgets.QMessageBox.ButtonRole.ActionRole
        ]
        return button

    def test_a_refusal_is_explained_in_a_non_modal_plain_text_box(self):
        box = self.notice.show(
            "AI: Level 2 slab\n<b>x</b>\u202e",
            "Something was edited since.",
            self.discard,
        )
        self.assertTrue(box.isVisible())
        self.assertFalse(box.isModal())
        self.assertEqual(box.windowTitle(), UNDO_REFUSED_TITLE)
        self.assertEqual(box.textFormat(), QtCore.Qt.TextFormat.PlainText)
        self.assertIn("AI: Level 2 slab <b>x</b> could not be undone.", box.text())
        self.assertNotIn("\u202e", box.text())
        self.assertIn("Something was edited since.", box.text())
        self.assertIn("older undo steps", box.informativeText())
        self.assertIn("stay in the bid", box.informativeText())
        self.assertEqual(self.discard_button(box).text(), DISCARD_BUTTON_TEXT)
        close = box.button(QtWidgets.QMessageBox.StandardButton.Close)
        self.assertIs(box.defaultButton(), close)
        self.assertIs(box.escapeButton(), close)
        self.assertEqual(box.icon(), QtWidgets.QMessageBox.Icon.Warning)
        self.assertEqual(self.discards, [])

    def test_discard_entry_discards_once_and_closes_the_box(self):
        box = self.notice.show("AI: slab", "Edited.", self.discard)
        self.discard_button(box).click()
        self.assertEqual(self.discards, [True])
        self.assertFalse(box.isVisible())
        self.assertEqual(self.notice.last_result, "discarded")

    def test_a_discard_that_cannot_happen_keeps_the_box_open_and_says_why(self):
        self.discard_result = False
        box = self.notice.show("AI: slab", "Edited.", self.discard)
        self.discard_button(box).click()
        self.assertTrue(box.isVisible())
        self.assertEqual(box.informativeText(), DISCARD_FAILED_TEXT)
        self.assertEqual(self.notice.last_result, "kept")

    def test_closing_keeps_the_entry(self):
        box = self.notice.show("AI: slab", "Edited.", self.discard)
        box.button(QtWidgets.QMessageBox.StandardButton.Close).click()
        self.assertEqual(self.discards, [])
        self.assertFalse(box.isVisible())

    def test_a_new_refusal_replaces_the_open_box_and_cleanup_closes_it(self):
        first = self.notice.show("AI: one", "Edited.", self.discard)
        second = self.notice.show("AI: two", "Edited.", self.discard)
        self.assertFalse(first.isVisible())
        self.assertTrue(second.isVisible())
        self.discard_button(second).click()
        self.assertEqual(self.discards, [True])
        third = self.notice.show("AI: three", "Edited.", self.discard)
        self.notice.cleanup()
        self.assertFalse(third.isVisible())
        QtCore.QCoreApplication.sendPostedEvents(
            None, QtCore.QEvent.Type.DeferredDelete
        )
        self.assertFalse(isValid(third))

    def test_the_notice_is_owned_by_its_parent_and_boxes_by_the_parent_widget(self):
        window = QtWidgets.QWidget()
        self.addCleanup(window.deleteLater)
        notice = AiUndoRefusalNotice(lambda: window, parent=window)
        self.addCleanup(notice.cleanup)
        self.assertIs(notice.parent(), window)
        box = notice.show("AI: slab", "Edited.", self.discard)
        self.assertIs(box.parent(), window)


if __name__ == "__main__":
    unittest.main()
