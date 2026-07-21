import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PySide6 import QtCore, QtWidgets
from ost_visualizer.presentation.components.mesh_view import OpenGLViewer
from ost_visualizer.presentation.controllers.menu_controller import MenuController
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.windows.components.window import DetachedPageViewWindow


def _app():
    app = QtWidgets.QApplication.instance()
    return app or QtWidgets.QApplication([])


class _Access:
    @staticmethod
    def is_allowed(feature):
        return feature == Feature.SELECT_PLAN_ITEMS


class _PlanWidget(QtWidgets.QWidget):
    def __init__(self, page_uid, parent=None):
        super().__init__(parent)
        self.current_page_uid = page_uid
        self.has_takeoff_objects = True
        self.has_selected_takeoffs = False
        self.selected_areas = []

    def select_takeoffs_in_area(self, area_uid):
        self.selected_areas.append(area_uid)


class _PageSettings(QtWidgets.QWidget):
    def __init__(self, area_uid, parent=None):
        super().__init__(parent)
        self._area_uid = area_uid

    def get_selected_area_uid(self):
        return self._area_uid


class _Manager:
    def __init__(self, window=None):
        self.window = window

    def get_window(self):
        return self.window


class _DetachedWindow(QtWidgets.QMainWindow):
    current_area_selection_target = DetachedPageViewWindow.current_area_selection_target

    def __init__(self, page_uid, area_uid):
        super().__init__()
        self._is_closing = False
        self.plan_view = _PlanWidget(page_uid, self)
        child = QtWidgets.QLineEdit(self.plan_view)
        self.setCentralWidget(self.plan_view)
        self.focus_child = child
        self.page_data = SimpleNamespace(
            page=SimpleNamespace(uid=page_uid),
            page_area_selections={page_uid: area_uid},
        )


class _Shell(QtWidgets.QMainWindow):
    _widget_top_level = staticmethod(MainWindow._widget_top_level)
    _detached_plan_windows = MainWindow._detached_plan_windows
    resolve_current_area_selection_context = (
        MainWindow.resolve_current_area_selection_context
    )

    def __init__(self):
        super().__init__()
        self.plan_view = _PlanWidget("main-page", self)
        self.focus_child = QtWidgets.QLineEdit(self.plan_view)
        self._page_settings_bar = _PageSettings("main-area", self)
        self._annotation_view_manager = _Manager()
        self._view_window_manager = _Manager()

    @staticmethod
    def is_takeoff_tab_active():
        return True

    def get_takeoff_plan_view(self):
        return self.plan_view

    def get_page_settings_bar(self):
        return self._page_settings_bar


def _controller(shell):
    controller = MenuController.__new__(MenuController)
    controller.window = shell
    controller.ui_access_manager = _Access()
    controller.handlers = SimpleNamespace(
        ui_event=SimpleNamespace(refresh_toolbar=lambda: None)
    )
    return controller


class CurrentAreaSelectionRoutingTests(unittest.TestCase):
    def setUp(self):
        _app()
        self.shell = _Shell()
        self.detached = _DetachedWindow("detached-page", "detached-area")
        self.shell._annotation_view_manager.window = self.detached

    def tearDown(self):
        self.detached.close()
        self.shell.close()
        _app().processEvents()

    def test_main_view_selection_uses_main_area(self):
        with patch.object(
            QtWidgets.QApplication, "focusWidget", return_value=self.shell.focus_child
        ), patch.object(
            QtWidgets.QApplication, "activeWindow", return_value=self.shell
        ):
            _controller(self.shell)._select_objects_in_current_area()
        self.assertEqual(self.shell.plan_view.selected_areas, ["main-area"])
        self.assertEqual(self.detached.plan_view.selected_areas, [])

    def test_menu_focus_resolves_owner_without_active_window_assumption(self):
        menu = QtWidgets.QMenu(self.shell)
        with patch.object(
            QtWidgets.QApplication, "focusWidget", return_value=menu
        ), patch.object(QtWidgets.QApplication, "activeWindow", return_value=menu):
            _controller(self.shell)._select_objects_in_current_area()
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
            _controller(self.shell)._select_objects_in_current_area()
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
            _controller(self.shell)._select_objects_in_current_area()
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
            _controller(self.shell)._select_objects_in_current_area()
        self.assertIs(target.parent, self.detached)
        self.assertEqual(self.detached.plan_view.selected_areas, ["detached-area"])
        self.assertEqual(self.shell.plan_view.selected_areas, [])

    def test_closed_surface_does_not_receive_action_and_warns_with_top_level_parent(
        self,
    ):
        self.detached._is_closing = True
        controller = _controller(self.shell)
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
        controller = _controller(self.shell)
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

    def test_native_surface_notifications_use_real_top_level_without_qt_warning(self):
        messages = []

        def handler(_message_type, _context, message):
            messages.append(message)

        host = QtWidgets.QMainWindow()
        container = QtWidgets.QWidget(host)
        viewer = OpenGLViewer(container, SimpleNamespace())
        viewer.hide()
        host.setCentralWidget(container)
        previous = QtCore.qInstallMessageHandler(handler)
        try:
            host.show()
            _app().processEvents()
            viewer._connect_surface_notifications()
            self.assertIs(viewer._surface_window, host.windowHandle())
        finally:
            QtCore.qInstallMessageHandler(previous)
            viewer.cleanup()
            host.close()
            _app().processEvents()
        self.assertFalse(
            any("QWidgetWindow must be a top level window" in msg for msg in messages)
        )


if __name__ == "__main__":
    unittest.main()
