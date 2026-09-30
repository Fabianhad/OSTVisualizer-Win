import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QComboBox
from shiboken6 import delete
from ost_visualizer.presentation.utils.combo_identity import (
    AmbiguousComboIdentityError,
    resolve_editable_combo_uid,
)


class ResolveEditableComboUidTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.addItem("Area", "first")
        self.combo.addItem("Area", "second")
        self.combo.addItem(" Unique ", "unique")
        self.addCleanup(delete, self.combo)

    def test_selected_duplicate_retains_its_exact_uid(self):
        self.combo.setCurrentIndex(1)
        self.assertEqual(resolve_editable_combo_uid(self.combo), "second")

    def test_unselected_duplicate_text_is_rejected(self):
        self.combo.setCurrentIndex(-1)
        self.combo.setEditText(" area ")
        with self.assertRaises(AmbiguousComboIdentityError):
            resolve_editable_combo_uid(self.combo)

    def test_unique_typed_label_resolves_case_and_whitespace(self):
        self.combo.setCurrentIndex(-1)
        self.combo.setEditText("UNIQUE")
        self.assertEqual(resolve_editable_combo_uid(self.combo), "unique")

    def test_empty_or_unrecognized_draft_does_not_reuse_previous_uid(self):
        for text in ("", "   ", "missing"):
            with self.subTest(text=text):
                self.combo.setCurrentIndex(0)
                self.combo.setEditText(text)
                self.assertIsNone(resolve_editable_combo_uid(self.combo))
