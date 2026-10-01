import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.utils.messagebox import (
    confirm_delete_conditions,
    confirm_multi_delete,
    confirm_save_discard_cancel,
)
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


class ConfirmDeleteConditionsChoiceTests(unittest.TestCase):
    NAMES = [("u0", "Zero"), ("u1", "One"), ("u2", "Two")]

    def _confirm(self, choices):
        _dialog_lifecycle_support__app()
        owner = QtWidgets.QWidget()
        self.addCleanup(owner.deleteLater)
        remaining_choices = iter(choices)
        offered = []
        selected = {}
        standard = QtWidgets.QMessageBox.StandardButton

        def pick(box):
            offered.append([button.text().replace("&", "") for button in box.buttons()])
            choice = next(remaining_choices)
            for button in box.buttons():
                if choice == "all" and button.text() == "Yes to all":
                    selected["button"] = button
                elif choice == "yes" and box.standardButton(button) == standard.Yes:
                    selected["button"] = button
                elif choice == "no" and box.standardButton(button) == standard.No:
                    selected["button"] = button
            return 0

        with patch.object(QtWidgets.QMessageBox, "exec", pick), patch.object(
            QtWidgets.QMessageBox, "clickedButton", lambda _box: selected["button"]
        ):
            result = confirm_delete_conditions(owner, self.NAMES)
        return result, offered, list(remaining_choices)

    def test_each_condition_is_confirmed_or_declined_individually(self):
        result, offered, unused = self._confirm(["yes", "no", "yes"])
        self.assertEqual(result, ["u0", "u2"])
        self.assertEqual(len(offered), 3)
        self.assertEqual(unused, [])

    def test_declining_every_condition_deletes_nothing(self):
        result, offered, _unused = self._confirm(["no", "no", "no"])
        self.assertEqual(result, [])
        self.assertEqual(len(offered), 3)

    def test_yes_to_all_confirms_current_and_remaining_without_more_prompts(self):
        result, offered, _unused = self._confirm(["no", "all"])
        self.assertEqual(result, ["u1", "u2"])
        self.assertEqual(len(offered), 2)

    def test_yes_to_all_is_only_offered_while_more_conditions_remain(self):
        _result, offered, _unused = self._confirm(["yes", "yes", "yes"])
        self.assertEqual(
            ["Yes to all" in texts for texts in offered], [True, True, False]
        )


class ConfirmMultiDeleteTests(unittest.TestCase):
    ITEMS = [("Used", "1"), ("Free", "2")]

    def test_only_unused_items_are_confirmed_and_returned(self):
        yes = QtWidgets.QMessageBox.StandardButton.Yes
        with patch.object(QtWidgets.QMessageBox, "question", return_value=yes) as ask:
            result = confirm_multi_delete(None, "Delete", self.ITEMS, {"1"})
        self.assertEqual(result, [("Free", "2")])
        message = ask.call_args.args[2]
        self.assertIn('Cannot delete "Used" because it is in use.', message)
        self.assertIn("Delete the other 1 item(s)?", message)

    def test_declining_mixed_delete_returns_none(self):
        no = QtWidgets.QMessageBox.StandardButton.No
        with patch.object(QtWidgets.QMessageBox, "question", return_value=no):
            self.assertIsNone(confirm_multi_delete(None, "Delete", self.ITEMS, {"1"}))

    def test_all_items_in_use_warns_without_asking(self):
        with patch.object(QtWidgets.QMessageBox, "question") as ask, patch.object(
            QtWidgets.QMessageBox, "warning"
        ) as warn:
            result = confirm_multi_delete(None, "Delete", self.ITEMS, {"1", "2"})
        self.assertIsNone(result)
        ask.assert_not_called()
        warn.assert_called_once()
        self.assertIn('"Free"', warn.call_args.args[2])

    def test_unused_items_ask_with_count_and_yes_returns_all(self):
        yes = QtWidgets.QMessageBox.StandardButton.Yes
        with patch.object(QtWidgets.QMessageBox, "question", return_value=yes) as ask:
            result = confirm_multi_delete(None, "Delete", self.ITEMS, set())
        self.assertEqual(result, self.ITEMS)
        self.assertEqual(ask.call_args.args[2], "Delete 2 item(s)?")


class ConfirmSaveDiscardCancelTests(unittest.TestCase):
    def test_reply_maps_to_save_discard_or_cancel(self):
        buttons = QtWidgets.QMessageBox.StandardButton
        for reply, expected in (
            (buttons.Yes, True),
            (buttons.No, False),
            (buttons.Cancel, None),
        ):
            with self.subTest(reply=reply):
                with patch.object(
                    QtWidgets.QMessageBox, "question", return_value=reply
                ):
                    self.assertIs(
                        confirm_save_discard_cancel(None, "Title", "Message"),
                        expected,
                    )
