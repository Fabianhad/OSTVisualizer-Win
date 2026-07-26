import unittest
from types import SimpleNamespace

from PySide6 import QtCore, QtWidgets

from ost_visualizer.presentation.builders.component_builder import (
    _PlanRibbonToolBar,
    _PlanToolbarLayoutSyncFilter,
)
from ost_visualizer.presentation.components.popup_tracking_combo import (
    PopupTrackingComboBox,
    parse_zoom_percent,
    update_zoom_combo,
)
from ost_visualizer.presentation.windows.mesh_view_window import MeshViewWindow


class ComponentBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_plan_toolbar_layout_filter_coalesces_event_burst(self):
        calls = []
        watched = QtCore.QObject()
        sync_filter = _PlanToolbarLayoutSyncFilter(lambda: calls.append("sync"))
        for event_type in (
            QtCore.QEvent.Type.Show,
            QtCore.QEvent.Type.Resize,
            QtCore.QEvent.Type.LayoutRequest,
        ):
            sync_filter.eventFilter(watched, QtCore.QEvent(event_type))
        self.assertEqual(calls, [])
        self.app.processEvents()
        self.assertEqual(calls, ["sync"])

        sync_filter.eventFilter(
            watched, QtCore.QEvent(QtCore.QEvent.Type.LayoutRequest)
        )
        self.app.processEvents()
        self.assertEqual(calls, ["sync", "sync"])

    def test_plan_ribbon_toolbar_honors_preferred_vertical_docked_height(self):
        host = QtWidgets.QMainWindow()
        toolbar = _PlanRibbonToolBar(host)
        toolbar.setOrientation(QtCore.Qt.Orientation.Vertical)
        host.addToolBar(QtCore.Qt.ToolBarArea.RightToolBarArea, toolbar)
        toolbar.set_preferred_docked_height(240)
        self.assertGreaterEqual(toolbar.sizeHint().height(), 240)
        self.assertGreaterEqual(toolbar.minimumSizeHint().height(), 240)

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

    def test_detached_mesh_invalid_zoom_text_restores_current_zoom(self):
        combo = PopupTrackingComboBox()
        combo.setEditable(True)
        combo.setEditText("inf")
        zoom_writes = []
        window = MeshViewWindow.__new__(MeshViewWindow)
        window._zoom_combo = combo
        window.viewer = SimpleNamespace(
            get_zoom_percent=lambda: 250.0,
            set_zoom_percent=zoom_writes.append,
        )
        MeshViewWindow._on_zoom_text_entered(window)
        self.assertEqual(zoom_writes, [])
        self.assertEqual(combo.currentText(), "250%")

    def test_detached_mesh_ignored_tiny_zoom_displays_actual_zoom(self):
        combo = PopupTrackingComboBox()
        combo.setEditable(True)
        combo.setEditText("0.0000001")
        zoom_writes = []
        window = MeshViewWindow.__new__(MeshViewWindow)
        window._zoom_combo = combo
        window.viewer = SimpleNamespace(
            get_zoom_percent=lambda: 250.0,
            set_zoom_percent=zoom_writes.append,
        )
        MeshViewWindow._on_zoom_text_entered(window)
        self.assertEqual(zoom_writes, [0.0000001])
        self.assertEqual(combo.currentText(), "250%")

    def test_detached_mesh_ignored_zoom_button_displays_actual_zoom(self):
        combo = PopupTrackingComboBox()
        combo.setEditable(True)
        zoom_writes = []
        window = MeshViewWindow.__new__(MeshViewWindow)
        window._zoom_combo = combo
        window.viewer = SimpleNamespace(
            get_zoom_percent=lambda: 250.0,
            set_zoom_percent=zoom_writes.append,
        )
        MeshViewWindow._on_zoom_in(window)
        self.assertEqual(zoom_writes, [287.5])
        self.assertEqual(combo.currentText(), "250%")


if __name__ == "__main__":
    unittest.main()
