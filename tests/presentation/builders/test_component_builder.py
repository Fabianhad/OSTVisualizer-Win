import unittest
from types import SimpleNamespace
from ost_visualizer.presentation.actions.action_ids import (
    ACTION_CONDITIONS_SIDEBAR,
    ACTION_LAYERS_SIDEBAR,
    ACTION_PAN_SIDEBAR,
)
from ost_visualizer.presentation.components.menu_builder import MenuBuilder
from ost_visualizer.presentation.config import SIDEBAR_MIN_WIDTH
from ost_visualizer.presentation.managers.icon_manager import IconId, IconManager
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


class SidebarToggleBuilderTests(unittest.TestCase):
    _main_components = cross_surface.SceneControlPresentationTests._main_components

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        _toolbar_visibility_support_register_test_fonts()

    def setUp(self):
        self.bundle, _zoom = self._main_components()
        self.addCleanup(self.app.processEvents)

    def sidebar_actions(self):
        return {
            ACTION_CONDITIONS_SIDEBAR: self.bundle.conditions_toggle_action,
            ACTION_LAYERS_SIDEBAR: self.bundle.layers_toggle_action,
            ACTION_PAN_SIDEBAR: self.bundle.pan_toggle_action,
        }

    def test_the_toolbar_and_the_view_menu_list_the_sidebar_toggles_in_the_same_order(
        self,
    ):
        by_action = {id(action): key for key, action in self.sidebar_actions().items()}
        toolbar_order = [
            by_action[id(action)]
            for action in self.bundle.view_toolbar.actions()
            if id(action) in by_action
        ]
        menu_items = MenuBuilder(None, {})._get_menu_definition()["View"]
        menu_order = [
            item[1]
            for item in menu_items
            if item[0] == "shared" and item[1] in self.sidebar_actions()
        ]
        expected = [
            ACTION_PAN_SIDEBAR,
            ACTION_CONDITIONS_SIDEBAR,
            ACTION_LAYERS_SIDEBAR,
        ]
        self.assertEqual(toolbar_order, expected)
        self.assertEqual(menu_order, expected)
        self.assertEqual(toolbar_order, menu_order)

    def test_the_toggles_follow_the_on_screen_sidebar_layout_top_to_bottom(self):
        bundle = self.bundle
        left = bundle.left_splitter
        self.assertIs(left.widget(0), bundle.conditions_sidebar)
        self.assertIs(left.widget(1), bundle.bid_layers_sidebar)
        column = bundle.left_column_splitter
        self.assertIs(column.widget(0), bundle.pan_sidebar)
        self.assertIs(column.widget(1), left)
        self.assertEqual(column.orientation(), QtCore.Qt.Orientation.Vertical)
        self.assertIs(bundle.takeoff_splitter.widget(0), column)

    def test_the_pan_toggle_is_checkable_labelled_and_themed_like_its_siblings(self):
        pan = self.bundle.pan_toggle_action
        sibling = self.bundle.layers_toggle_action
        self.assertTrue(pan.isCheckable())
        self.assertEqual(pan.isChecked(), not self.bundle.pan_sidebar.isHidden())
        self.assertEqual(pan.text(), "Pan Sidebar")
        self.assertEqual(pan.toolTip(), "Hide/Show Pan Sidebar")
        self.assertFalse(pan.icon().isNull())
        self.assertEqual(
            pan.icon().cacheKey(), IconManager.icon(IconId.PAN_SIDEBAR).cacheKey()
        )
        self.assertEqual(pan.isCheckable(), sibling.isCheckable())
        self.assertIs(pan.parent(), sibling.parent())

    def test_the_pan_toggle_button_has_an_accessible_name_and_tooltip(self):
        button = self.bundle.view_toolbar.widgetForAction(self.bundle.pan_toggle_action)
        self.assertIsInstance(button, QtWidgets.QToolButton)
        self.assertEqual(button.accessibleName(), "Pan Sidebar")
        self.assertEqual(button.toolTip(), "Hide/Show Pan Sidebar")
        self.assertTrue(button.isCheckable())

    def test_the_pan_sidebar_starts_hidden_and_the_column_follows_the_two_sidebars(
        self,
    ):
        self.assertTrue(self.bundle.pan_sidebar.isHidden())
        self.assertFalse(self.bundle.pan_toggle_action.isChecked())
        self.assertFalse(self.bundle.left_column_splitter.isHidden())

    def test_the_column_keeps_the_sidebar_width_and_gives_the_spare_height_to_the_top(
        self,
    ):
        column = self.bundle.left_column_splitter
        self.assertEqual(column.minimumWidth(), SIDEBAR_MIN_WIDTH)
        self.assertEqual(column.widget(0).sizePolicy().verticalStretch(), 0)
        self.assertEqual(column.widget(1).sizePolicy().verticalStretch(), 1)
        self.assertFalse(column.isCollapsible(0))
        self.assertTrue(column.isCollapsible(1))

    def test_the_conditions_pane_absorbs_height_changes_and_layers_keeps_its_size(self):
        left = self.bundle.left_splitter
        self.assertIs(left.widget(0), self.bundle.conditions_sidebar)
        self.assertIs(left.widget(1), self.bundle.bid_layers_sidebar)
        self.assertEqual(left.widget(0).sizePolicy().verticalStretch(), 1)
        self.assertEqual(left.widget(1).sizePolicy().verticalStretch(), 0)
