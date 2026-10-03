import unittest
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.presentation.controllers.menu_controller import MenuController
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.windows.components.window import DetachedPageViewWindow
from PySide6 import QtCore, QtWidgets
from tests.integration.selection.area_routing_support import (
    _Access as _area_routing_support__Access,
    _DetachedWindow as _area_routing_support__DetachedWindow,
    _Manager as _area_routing_support__Manager,
    _PageSettings as _area_routing_support__PageSettings,
    _PlanWidget as _area_routing_support__PlanWidget,
    _Shell as _area_routing_support__Shell,
    _app as _area_routing_support__app,
    _controller as _area_routing_support__controller,
)


class CurrentAreaSelectionRoutingTests(unittest.TestCase):
    def setUp(self):
        _area_routing_support__app()
        self.shell = _area_routing_support__Shell()
        self.detached = _area_routing_support__DetachedWindow(
            "detached-page", "detached-area"
        )
        self.shell._annotation_view_manager.window = self.detached

    def tearDown(self):
        self.detached.close()
        self.shell.close()
        _area_routing_support__app().processEvents()

    def test_main_view_selection_uses_main_area(self):
        with patch.object(
            QtWidgets.QApplication, "focusWidget", return_value=self.shell.focus_child
        ), patch.object(
            QtWidgets.QApplication, "activeWindow", return_value=self.shell
        ):
            _area_routing_support__controller(
                self.shell
            )._select_objects_in_current_area()
        self.assertEqual(self.shell.plan_view.selected_areas, ["main-area"])
        self.assertEqual(self.detached.plan_view.selected_areas, [])

    def test_menu_focus_resolves_owner_without_active_window_assumption(self):
        menu = QtWidgets.QMenu(self.shell)
        with patch.object(
            QtWidgets.QApplication, "focusWidget", return_value=menu
        ), patch.object(QtWidgets.QApplication, "activeWindow", return_value=menu):
            _area_routing_support__controller(
                self.shell
            )._select_objects_in_current_area()
        self.assertEqual(self.shell.plan_view.selected_areas, ["main-area"])
        menu.close()

    def test_focus_is_sampled_once_during_command_dispatch(self):
        stale_window = QtWidgets.QWidget()
        stale_child = QtWidgets.QLineEdit(stale_window)
        with patch.object(
            QtWidgets.QApplication,
            "focusWidget",
            side_effect=[self.shell.focus_child, stale_child],
        ) as focus_widget, patch.object(
            QtWidgets.QApplication, "activeWindow", return_value=self.shell
        ):
            _area_routing_support__controller(
                self.shell
            )._select_objects_in_current_area()
        self.assertEqual(focus_widget.call_count, 1)
        self.assertEqual(self.shell.plan_view.selected_areas, ["main-area"])
        stale_window.close()

    def test_no_active_plan_surface_fails_safely(self):
        with patch.object(
            QtWidgets.QApplication, "focusWidget", return_value=None
        ), patch.object(
            QtWidgets.QApplication, "activeWindow", return_value=None
        ), patch(
            "ost_visualizer.presentation.controllers.menu_controller.show_warning"
        ) as warning:
            _area_routing_support__controller(
                self.shell
            )._select_objects_in_current_area()
        warning.assert_called_once()
        self.assertEqual(self.shell.plan_view.selected_areas, [])

    def test_detached_child_focus_routes_selection_to_detached_surface(self):
        with patch.object(
            QtWidgets.QApplication,
            "focusWidget",
            return_value=self.detached.focus_child,
        ), patch.object(
            QtWidgets.QApplication, "activeWindow", return_value=self.detached
        ):
            target = self.shell.resolve_current_area_selection_context()
            _area_routing_support__controller(
                self.shell
            )._select_objects_in_current_area()
        self.assertIs(target.parent, self.detached)
        self.assertEqual(self.detached.plan_view.selected_areas, ["detached-area"])
        self.assertEqual(self.shell.plan_view.selected_areas, [])

    def test_closed_surface_does_not_receive_action_and_warns_with_top_level_parent(
        self,
    ):
        self.detached._is_closing = True
        controller = _area_routing_support__controller(self.shell)
        with patch.object(
            QtWidgets.QApplication,
            "focusWidget",
            return_value=self.detached.focus_child,
        ), patch.object(
            QtWidgets.QApplication, "activeWindow", return_value=self.detached
        ), patch(
            "ost_visualizer.presentation.controllers.menu_controller.show_warning"
        ) as warning:
            controller._select_objects_in_current_area()
        self.assertEqual(self.detached.plan_view.selected_areas, [])
        warning.assert_called_once()
        self.assertIs(warning.call_args.args[0], self.shell)

    def test_unknown_stale_top_level_does_not_fall_back_to_main_surface(self):
        stale_window = QtWidgets.QWidget()
        stale_child = QtWidgets.QLineEdit(stale_window)
        controller = _area_routing_support__controller(self.shell)
        with patch.object(
            QtWidgets.QApplication, "focusWidget", return_value=stale_child
        ), patch.object(
            QtWidgets.QApplication, "activeWindow", return_value=self.shell
        ), patch(
            "ost_visualizer.presentation.controllers.menu_controller.show_warning"
        ):
            controller._select_objects_in_current_area()
        self.assertEqual(self.shell.plan_view.selected_areas, [])
        stale_window.close()

    def _select_with_focus(self, controller, focus_widget, active_window):
        with patch.object(
            QtWidgets.QApplication, "focusWidget", return_value=focus_widget
        ), patch.object(
            QtWidgets.QApplication, "activeWindow", return_value=active_window
        ), patch(
            "ost_visualizer.presentation.controllers.menu_controller.show_warning"
        ) as warning:
            controller._select_objects_in_current_area()
        return warning

    def test_menu_hosted_inside_another_menu_falls_back_to_active_window(self):
        outer = QtWidgets.QMenu(self.shell)
        holder = QtWidgets.QWidget(outer)
        menu = QtWidgets.QMenu(holder)
        self.assertIs(menu.parentWidget().window(), outer)
        warning = self._select_with_focus(
            _area_routing_support__controller(self.shell), menu, self.shell
        )
        warning.assert_not_called()
        self.assertEqual(self.shell.plan_view.selected_areas, ["main-area"])
        menu.close()
        outer.close()

    def test_main_view_without_takeoff_tab_warns_instead_of_selecting(self):
        controller = _area_routing_support__controller(self.shell)
        warning = self._select_with_focus(
            controller, self.shell.focus_child, self.shell
        )
        warning.assert_not_called()
        self.assertEqual(self.shell.plan_view.selected_areas, ["main-area"])
        self.shell.is_takeoff_tab_active = lambda: False
        warning = self._select_with_focus(
            controller, self.shell.focus_child, self.shell
        )
        warning.assert_called_once()
        self.assertIs(warning.call_args.args[0], self.shell)
        self.assertEqual(self.shell.plan_view.selected_areas, ["main-area"])

    def test_main_view_without_selected_area_selects_with_no_area_filter(self):
        self.shell._page_settings_bar._area_uid = ""
        warning = self._select_with_focus(
            _area_routing_support__controller(self.shell),
            self.shell.focus_child,
            self.shell,
        )
        warning.assert_not_called()
        self.assertEqual(self.shell.plan_view.selected_areas, [None])

    def test_denied_select_permission_neither_selects_nor_warns(self):
        controller = _area_routing_support__controller(self.shell)
        controller.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: False
        )
        warning = self._select_with_focus(
            controller, self.shell.focus_child, self.shell
        )
        warning.assert_not_called()
        self.assertEqual(self.shell.plan_view.selected_areas, [])
        self.assertEqual(self.detached.plan_view.selected_areas, [])
        controller.ui_access_manager = _area_routing_support__Access()
        self._select_with_focus(controller, self.shell.focus_child, self.shell)
        self.assertEqual(self.shell.plan_view.selected_areas, ["main-area"])

    def test_detached_plan_showing_another_page_is_not_selected(self):
        controller = _area_routing_support__controller(self.shell)
        warning = self._select_with_focus(
            controller, self.detached.focus_child, self.detached
        )
        warning.assert_not_called()
        self.assertEqual(self.detached.plan_view.selected_areas, ["detached-area"])
        self.detached.plan_view.current_page_uid = "stale-page"
        warning = self._select_with_focus(
            controller, self.detached.focus_child, self.detached
        )
        warning.assert_called_once()
        self.assertIs(warning.call_args.args[0], self.shell)
        self.assertEqual(self.detached.plan_view.selected_areas, ["detached-area"])
        self.assertEqual(self.shell.plan_view.selected_areas, [])

    def test_toolbar_refreshes_only_after_a_successful_selection(self):
        refreshes = []
        controller = _area_routing_support__controller(self.shell)
        controller.handlers.ui_event.refresh_toolbar = lambda: refreshes.append(True)
        self._select_with_focus(controller, self.shell.focus_child, self.shell)
        self.assertEqual(self.shell.plan_view.selected_areas, ["main-area"])
        self.assertEqual(refreshes, [True])
        self._select_with_focus(controller, None, None)
        self.assertEqual(refreshes, [True])
