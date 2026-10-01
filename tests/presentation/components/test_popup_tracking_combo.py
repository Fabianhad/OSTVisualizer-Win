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
        self.assertEqual(parse_zoom_percent("50"), 50.0)
        self.assertEqual(parse_zoom_percent("12.5%"), 12.5)
        for value in (
            "",
            "%",
            "invalid",
            "0",
            "0%",
            "-0",
            "-5",
            "-5%",
            "nan",
            "NaN%",
            "inf",
            "-inf",
            "1e400",
        ):
            with self.subTest(value=value):
                self.assertIsNone(parse_zoom_percent(value))

    def test_zoom_combo_update_ignores_invalid_factor_and_restores_signals(self):
        combo = PopupTrackingComboBox()
        combo.setEditable(True)
        combo.addItems(["50%", "100%", "200%"])
        combo.setCurrentIndex(1)
        emitted = []
        combo.currentIndexChanged.connect(
            lambda index: emitted.append(("index", index))
        )
        combo.lineEdit().textChanged.connect(
            lambda text: emitted.append(("text", text))
        )
        for invalid in (float("inf"), float("-inf"), float("nan"), 0.0, -1.0):
            with self.subTest(factor=invalid):
                update_zoom_combo(combo, invalid)
                self.assertEqual(combo.currentText(), "100%")
                self.assertEqual(combo.currentIndex(), 1)
        self.assertEqual(emitted, [])
        update_zoom_combo(combo, 1.25)
        self.assertEqual(combo.currentText(), "125%")
        self.assertEqual(combo.currentIndex(), -1)
        self.assertFalse(combo.signalsBlocked())
        self.assertFalse(combo.lineEdit().signalsBlocked())
        self.assertEqual(emitted, [])
        combo.blockSignals(True)
        combo.lineEdit().blockSignals(True)
        update_zoom_combo(combo, 1.5)
        self.assertEqual(combo.currentText(), "150%")
        self.assertTrue(combo.signalsBlocked())
        self.assertTrue(combo.lineEdit().signalsBlocked())
        combo.blockSignals(False)
        combo.lineEdit().blockSignals(False)
        combo.lineEdit().setText("175%")
        self.assertEqual(emitted, [("text", "175%")])

    def test_popup_signals_emit_immediately_without_hidden_delay(self):
        combo = PopupTrackingComboBox()
        combo.addItems(["100%"])
        events = []
        combo.popup_shown.connect(lambda: events.append("shown"))
        combo.popup_hidden.connect(lambda: events.append("hidden"))
        try:
            combo.showPopup()
            self.assertEqual(events, ["shown"])
            combo.hidePopup()
            self.assertEqual(events, ["shown", "hidden"])
        finally:
            combo.hidePopup()
            combo.deleteLater()

    def test_popup_hidden_is_deferred_and_cancelled_by_reshow(self):
        combo = PopupTrackingComboBox(popup_hidden_delay_ms=30)
        combo.addItems(["100%"])
        events = []
        combo.popup_shown.connect(lambda: events.append("shown"))
        combo.popup_hidden.connect(lambda: events.append("hidden"))
        try:
            combo.showPopup()
            combo.hidePopup()
            self.assertEqual(events, ["shown"])
            combo.showPopup()
            QtTest.QTest.qWait(80)
            self.assertEqual(events, ["shown", "shown"])
            combo.hidePopup()
            self.assertEqual(events, ["shown", "shown"])
            QtTest.QTest.qWait(80)
            self.assertEqual(events, ["shown", "shown", "hidden"])
        finally:
            combo.hidePopup()
            combo.deleteLater()
