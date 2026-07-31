import unittest
from types import SimpleNamespace
from PySide6 import QtCore, QtWidgets
from ost_visualizer.presentation.builders.component_builder import (
    _PlanRibbonToolBar,
    _PlanToolbarLayoutSyncFilter,
    _TakeoffViewSelectorController,
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

    def _view_selector(
        self,
        current_index=0,
        *,
        view_3d_visible=True,
        view_2d_visible=True,
    ):
        host = QtWidgets.QWidget()
        host.resize(400, 300)
        layout = QtWidgets.QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QtWidgets.QToolBar(host)
        view_3d_action = toolbar.addWidget(QtWidgets.QToolButton())
        view_2d_action = toolbar.addWidget(QtWidgets.QToolButton())
        view_3d_action.setVisible(view_3d_visible)
        view_2d_action.setVisible(view_2d_visible)
        view_stack = QtWidgets.QStackedWidget(host)
        view_3d = QtWidgets.QWidget()
        view_2d = QtWidgets.QWidget()
        view_stack.addWidget(view_3d)
        view_stack.addWidget(view_2d)
        view_stack.setCurrentIndex(current_index)
        layout.addWidget(toolbar)
        layout.addWidget(view_stack, 1)
        controller = _TakeoffViewSelectorController(
            toolbar,
            view_stack,
            view_3d_action,
            view_2d_action,
        )
        host.show()
        self.app.processEvents()
        return SimpleNamespace(
            host=host,
            toolbar=toolbar,
            view_stack=view_stack,
            view_3d=view_3d,
            view_2d=view_2d,
            view_3d_action=view_3d_action,
            view_2d_action=view_2d_action,
            controller=controller,
        )

    def test_view_selector_initial_availability_matrix(self):
        for view_3d_visible, view_2d_visible, initial_index, expected in (
            (True, True, 1, (True, 1)),
            (False, True, 0, (False, 1)),
            (True, False, 1, (False, 0)),
            (False, False, 1, (False, 1)),
        ):
            with self.subTest(
                view_3d_visible=view_3d_visible,
                view_2d_visible=view_2d_visible,
            ):
                ui = self._view_selector(
                    current_index=initial_index,
                    view_3d_visible=view_3d_visible,
                    view_2d_visible=view_2d_visible,
                )
                self.assertEqual(ui.toolbar.isVisible(), expected[0])
                self.assertEqual(ui.view_stack.currentIndex(), expected[1])
                self.assertEqual(ui.view_stack.count(), 2)
                self.assertTrue(ui.view_stack.currentWidget().isVisible())
                ui.host.close()

    def test_view_selector_shows_only_when_both_views_are_available(self):
        ui = self._view_selector(current_index=0)
        both_views_height = ui.view_stack.height()
        self.assertTrue(ui.toolbar.isVisible())
        self.assertTrue(ui.view_3d.isVisible())
        ui.view_3d_action.setVisible(False)
        self.app.processEvents()
        self.assertFalse(ui.toolbar.isVisible())
        self.assertEqual(ui.view_stack.currentIndex(), 1)
        self.assertTrue(ui.view_2d.isVisible())
        self.assertGreater(ui.view_stack.height(), both_views_height)
        ui.view_3d_action.setVisible(True)
        self.app.processEvents()
        self.assertTrue(ui.toolbar.isVisible())
        self.assertEqual(ui.view_stack.currentIndex(), 1)
        ui.view_2d_action.setVisible(False)
        self.app.processEvents()
        self.assertFalse(ui.toolbar.isVisible())
        self.assertEqual(ui.view_stack.currentIndex(), 0)
        self.assertTrue(ui.view_3d.isVisible())
        ui.view_2d_action.setVisible(True)
        self.app.processEvents()
        self.assertTrue(ui.toolbar.isVisible())
        self.assertEqual(ui.view_stack.currentIndex(), 0)
        ui.host.close()

    def test_view_selector_handles_disabled_and_unavailable_views(self):
        ui = self._view_selector(current_index=1)
        changes = []
        ui.view_stack.currentChanged.connect(changes.append)
        ui.view_2d_action.setEnabled(False)
        self.assertFalse(ui.toolbar.isVisible())
        self.assertEqual(ui.view_stack.currentIndex(), 0)
        self.assertEqual(changes, [0])
        ui.view_3d_action.setEnabled(False)
        self.assertFalse(ui.toolbar.isVisible())
        self.assertEqual(ui.view_stack.currentIndex(), 0)
        self.assertEqual(changes, [0])
        ui.view_2d_action.setEnabled(True)
        self.assertFalse(ui.toolbar.isVisible())
        self.assertEqual(ui.view_stack.currentIndex(), 1)
        self.assertEqual(changes, [0, 1])
        ui.host.close()

    def test_view_selector_refresh_is_idempotent_and_preserves_valid_selection(self):
        ui = self._view_selector(current_index=1)
        changes = []
        ui.view_stack.currentChanged.connect(changes.append)
        for _ in range(5):
            ui.controller.refresh()
        self.assertTrue(ui.toolbar.isVisible())
        self.assertEqual(ui.view_stack.currentIndex(), 1)
        self.assertEqual(changes, [])
        ui.view_3d_action.setVisible(False)
        for _ in range(5):
            ui.controller.refresh()
        self.assertEqual(ui.view_stack.currentIndex(), 1)
        self.assertEqual(changes, [])
        ui.host.close()

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
