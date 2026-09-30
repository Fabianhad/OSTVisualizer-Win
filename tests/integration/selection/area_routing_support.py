import unittest
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.presentation.components.mesh_view import OpenGLViewer
from ost_visualizer.presentation.controllers.menu_controller import MenuController
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.windows.components.window import DetachedPageViewWindow
from PySide6 import QtCore, QtWidgets


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
