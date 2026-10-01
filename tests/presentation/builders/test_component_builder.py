import unittest
from types import SimpleNamespace
from ost_visualizer.presentation.builders.component_builder import (
    _PlanRibbonToolBar,
    _PlanToolbarLayoutSyncFilter,
    _TakeoffViewSelectorController,
)
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from shiboken6 import delete
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from shiboken6 import delete, isValid
import tests.integration.surfaces.test_presentation as cross_surface
from tests.presentation.components.toolbar_visibility_support import (
    register_test_fonts as _toolbar_visibility_support_register_test_fonts,
)


class ComponentBuilderLayoutTests(unittest.TestCase):
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
            consumed = sync_filter.eventFilter(watched, QtCore.QEvent(event_type))
            self.assertIs(consumed, False)
        self.assertEqual(calls, [])
        self.app.processEvents()
        self.assertEqual(calls, ["sync"])
        sync_filter.eventFilter(
            watched, QtCore.QEvent(QtCore.QEvent.Type.LayoutRequest)
        )
        self.assertEqual(calls, ["sync"])
        self.app.processEvents()
        self.assertEqual(calls, ["sync", "sync"])
        self.app.processEvents()
        self.assertEqual(calls, ["sync", "sync"])

    def test_plan_toolbar_layout_filter_ignores_unrelated_events(self):
        calls = []
        watched = QtCore.QObject()
        sync_filter = _PlanToolbarLayoutSyncFilter(lambda: calls.append("sync"))
        for event_type in (
            QtCore.QEvent.Type.Hide,
            QtCore.QEvent.Type.Move,
            QtCore.QEvent.Type.Paint,
            QtCore.QEvent.Type.MouseMove,
            QtCore.QEvent.Type.Timer,
        ):
            consumed = sync_filter.eventFilter(watched, QtCore.QEvent(event_type))
            self.assertIs(consumed, False)
        self.app.processEvents()
        self.assertEqual(calls, [])

    def test_plan_toolbar_layout_filter_syncs_when_installed_on_a_real_widget(self):
        calls = []
        host = QtWidgets.QWidget()
        self.addCleanup(delete, host)
        sync_filter = _PlanToolbarLayoutSyncFilter(lambda: calls.append("sync"), host)
        host.installEventFilter(sync_filter)
        host.resize(200, 100)
        host.show()
        self.app.processEvents()
        self.assertEqual(calls, ["sync"])
        host.resize(300, 150)
        self.app.processEvents()
        self.assertEqual(calls, ["sync", "sync"])

    def test_plan_toolbar_layout_filter_drops_callback_after_owner_destruction(self):
        calls = []
        owner = QtWidgets.QWidget()
        sync_filter = _PlanToolbarLayoutSyncFilter(lambda: calls.append("stale"), owner)
        sync_filter.eventFilter(owner, QtCore.QEvent(QtCore.QEvent.Type.LayoutRequest))
        delete(owner)
        self.assertFalse(isValid(sync_filter))
        self.app.processEvents()
        self.assertEqual(calls, [])

    def test_plan_ribbon_toolbar_honors_preferred_vertical_docked_height(self):
        host = QtWidgets.QMainWindow()
        self.addCleanup(delete, host)
        toolbar = _PlanRibbonToolBar(host)
        toolbar.setOrientation(QtCore.Qt.Orientation.Vertical)
        host.addToolBar(QtCore.Qt.ToolBarArea.RightToolBarArea, toolbar)
        self.assertFalse(toolbar.isFloating())
        baseline_hint = toolbar.sizeHint()
        baseline_minimum = toolbar.minimumSizeHint()
        self.assertLess(baseline_hint.height(), 240)
        self.assertLess(baseline_minimum.height(), 240)
        toolbar.set_preferred_docked_height(240)
        self.assertEqual(toolbar.sizeHint().height(), 240)
        self.assertEqual(toolbar.minimumSizeHint().height(), 240)
        self.assertEqual(toolbar.sizeHint().width(), baseline_hint.width())
        toolbar.set_preferred_docked_height(-5)
        self.assertEqual(toolbar.sizeHint(), baseline_hint)
        self.assertEqual(toolbar.minimumSizeHint(), baseline_minimum)
        toolbar.set_preferred_docked_height(240)
        toolbar.set_preferred_docked_height(0)
        self.assertEqual(toolbar.sizeHint(), baseline_hint)

    def test_plan_ribbon_toolbar_ignores_preferred_height_unless_vertical_and_docked(
        self,
    ):
        host = QtWidgets.QMainWindow()
        self.addCleanup(delete, host)
        docked_horizontal = _PlanRibbonToolBar(host)
        host.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, docked_horizontal)
        floating_vertical = _PlanRibbonToolBar()
        self.addCleanup(delete, floating_vertical)
        floating_vertical.setOrientation(QtCore.Qt.Orientation.Vertical)
        self.assertTrue(floating_vertical.isFloating())
        for name, toolbar in (
            ("docked horizontal", docked_horizontal),
            ("floating vertical", floating_vertical),
        ):
            with self.subTest(toolbar=name):
                baseline_hint = toolbar.sizeHint()
                baseline_minimum = toolbar.minimumSizeHint()
                toolbar.set_preferred_docked_height(500)
                self.assertEqual(toolbar.sizeHint(), baseline_hint)
                self.assertEqual(toolbar.minimumSizeHint(), baseline_minimum)

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
        ui.view_3d_action.setEnabled(True)
        self.assertTrue(ui.toolbar.isVisible())
        self.assertEqual(ui.view_stack.currentIndex(), 1)
        self.assertEqual(changes, [0, 1])
        ui.view_3d_action.setVisible(False)
        ui.view_3d_action.setEnabled(False)
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
        self.assertFalse(ui.toolbar.isVisible())
        self.assertEqual(ui.view_stack.currentIndex(), 1)
        self.assertEqual(changes, [])
        ui.host.close()


class TakeoffToolbarVisibilityTests(unittest.TestCase):
    _main_components = cross_surface.SceneControlPresentationTests._main_components

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        _toolbar_visibility_support_register_test_fonts()

    def setUp(self):
        self.bundle, self.zoom = self._main_components()
        self.controller = self.bundle.takeoff_toolbar_visibility
        self.toolbar = self.controller.parent()
        self.controller.apply_hidden_items(())

    def item(self, key):
        result = self.toolbar.findChild(QtWidgets.QWidgetAction, key)
        self.assertIsNotNone(result)
        return result

    def test_wrapped_command_buttons_preserve_native_toolbar_presentation(self):
        reference = QtWidgets.QToolBar()
        self.addCleanup(lambda: delete(reference))
        native_action = reference.addAction("Select")
        native_button = reference.widgetForAction(native_action)
        self.assertTrue(native_button.autoRaise())
        self.assertEqual(native_button.focusPolicy(), QtCore.Qt.FocusPolicy.NoFocus)
        self.assertEqual(
            native_button.toolButtonStyle(),
            QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly,
        )
        for key in (
            "select_tool",
            "place_tool",
            "pan_tool",
            "zoom_tool",
            "reset_view",
            "zoom_in",
            "zoom_out",
        ):
            action = self.item(key)
            button = self.toolbar.widgetForAction(action)
            with self.subTest(key=key):
                self.assertIsInstance(button, QtWidgets.QToolButton)
                self.assertIsNotNone(button.defaultAction())
                self.assertEqual(button.defaultAction().text(), action.text())
                self.assertEqual(button.autoRaise(), native_button.autoRaise())
                self.assertEqual(button.focusPolicy(), native_button.focusPolicy())
                self.assertEqual(
                    button.toolButtonStyle(), native_button.toolButtonStyle()
                )
