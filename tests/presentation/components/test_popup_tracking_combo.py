import unittest
from ost_visualizer.presentation.components.popup_tracking_combo import (
    PopupTrackingComboBox,
    parse_zoom_percent,
    update_zoom_combo,
)
from PySide6 import QtCore, QtGui, QtTest, QtWidgets


class ZoomComboEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_zoom_percent_parser_rejects_invalid_and_non_finite_values(self):
        self.assertEqual(parse_zoom_percent(" 125% "), 125.0)
        for value in ("", "invalid", "0", "-5", "nan", "inf", "-inf"):
            with self.subTest(value=value):
                self.assertIsNone(parse_zoom_percent(value))

    def test_zoom_combo_update_ignores_invalid_factor_and_restores_signals(self):
        combo = PopupTrackingComboBox()
        combo.setEditable(True)
        combo.setEditText("100%")
        update_zoom_combo(combo, float("inf"))
        self.assertEqual(combo.currentText(), "100%")
        update_zoom_combo(combo, 1.25)
        self.assertEqual(combo.currentText(), "125%")
        self.assertFalse(combo.signalsBlocked())
        self.assertFalse(combo.lineEdit().signalsBlocked())
        combo.blockSignals(True)
        combo.lineEdit().blockSignals(True)
        update_zoom_combo(combo, 1.5)
        self.assertEqual(combo.currentText(), "150%")
        self.assertTrue(combo.signalsBlocked())
        self.assertTrue(combo.lineEdit().signalsBlocked())
