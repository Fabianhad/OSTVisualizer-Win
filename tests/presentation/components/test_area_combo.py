import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.presentation.components.area_combo import AreaComboBox
from PySide6 import QtCore, QtGui, QtWidgets


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class AreaComboConditionBehaviorTests(unittest.TestCase):
    def test_area_combo_clears_deleted_selected_area_uid_on_reload(self):
        combo = AreaComboBox(None)
        combo.load_areas(
            [BidArea(uid="a1", bid_uid="b1", parent_uid="", name="Area 1", sequence=1)],
            selected_uid="a1",
        )
        self.assertEqual(combo.get_current_area_uid(), "a1")
        combo.load_areas([], selected_uid=None)
        self.assertEqual(combo.get_current_area_uid(), "")
        combo.set_current_area_uid("deleted")
        self.assertEqual(combo.get_current_area_uid(), "")

    def test_area_combo_popup_bold_state_does_not_style_display_text(self):
        combo = AreaComboBox(None)
        combo.load_areas(
            [BidArea(uid="a1", bid_uid="b1", parent_uid="", name="Area 1", sequence=1)],
            areas_with_takeoff={"0"},
            selected_uid="0",
        )
        self.assertTrue(combo._area_items["0"].font().bold())
        self.assertEqual(combo.lineEdit().text(), "(Unassigned)")
        self.assertFalse(combo.lineEdit().font().bold())
        combo.set_current_area_uid("")
        self.assertEqual(combo.lineEdit().text(), "(All Areas)")
        self.assertFalse(combo.lineEdit().font().bold())

    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls._quit_on_last_window_closed = cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.setQuitOnLastWindowClosed(cls._quit_on_last_window_closed)

    def tearDown(self):
        self.app.processEvents()
