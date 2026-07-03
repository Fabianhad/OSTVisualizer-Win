import unittest
from PySide6 import QtCore, QtWidgets
from ost_visualizer.presentation.dialogs.select_named_view_dialog import (
    SelectNamedViewDialog,
)


def _ensure_app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class SelectNamedViewDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _ensure_app()

    def test_named_view_combo_is_editable_with_contains_completion(self):
        dialog = SelectNamedViewDialog(
            [
                ("nv-1", "p1", "Page A", "Office Ceiling"),
                ("nv-2", "p2", "Page B", "Lobby Wall"),
            ]
        )
        combo = dialog._named_view_combo
        completer = combo.completer()
        self.assertTrue(combo.isEditable())
        self.assertEqual(
            combo.insertPolicy(), QtWidgets.QComboBox.InsertPolicy.NoInsert
        )
        self.assertIsNotNone(completer)
        self.assertEqual(
            completer.caseSensitivity(), QtCore.Qt.CaseSensitivity.CaseInsensitive
        )
        self.assertEqual(completer.filterMode(), QtCore.Qt.MatchFlag.MatchContains)

    def test_named_view_search_text_is_focused_and_selected(self):
        dialog = SelectNamedViewDialog(
            [
                ("nv-1", "p1", "Page A", "Office Ceiling"),
                ("nv-2", "p2", "Page B", "Lobby Wall"),
            ]
        )
        line_edit = dialog._named_view_combo.lineEdit()
        self.assertIsNotNone(line_edit)
        self.assertTrue(line_edit.hasSelectedText())
        self.assertEqual(
            line_edit.selectedText(), dialog._named_view_combo.currentText()
        )

    def test_accept_uses_exact_typed_named_view_match(self):
        dialog = SelectNamedViewDialog(
            [
                ("nv-1", "p1", "Page A", "Office Ceiling"),
                ("nv-2", "p2", "Page B", "Lobby Wall"),
            ]
        )
        dialog._named_view_combo.setEditText("lobby wall (page b)")
        dialog.accept()
        result = dialog.result_data()
        self.assertFalse(result.create_new)
        self.assertEqual(result.named_view_uid, "nv-2")

    def test_accept_ignores_unmatched_typed_text(self):
        dialog = SelectNamedViewDialog(
            [
                ("nv-1", "p1", "Page A", "Office Ceiling"),
                ("nv-2", "p2", "Page B", "Lobby Wall"),
            ]
        )
        dialog._named_view_combo.setCurrentIndex(0)
        dialog._named_view_combo.setEditText("Lobby")
        dialog.accept()
        result = dialog.result_data()
        self.assertFalse(result.create_new)
        self.assertEqual(result.named_view_uid, "")
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)


if __name__ == "__main__":
    unittest.main()
