import unittest
from unittest.mock import patch
from ost_visualizer.presentation.components.plan_view.components import input_handler
from PySide6 import QtCore, QtWidgets
from shiboken6 import isValid


class _PlanMenuHarness(QtWidgets.QWidget):
    _show_common_context_menu = (
        input_handler.InputHandlerMixin._show_common_context_menu
    )

    def _context_menu_owner(self):
        return self

    def _add_common_context_submenus(self, menu):
        return 0, None, None

    def _add_context_page_actions(self, menu, **options):
        pass

    def reset_ctrl_held(self):
        pass


class _OwnedPlanMenuHarness(_PlanMenuHarness):
    _context_menu_owner = input_handler.InputHandlerMixin._context_menu_owner
    _context_menu_owner_is_current = (
        input_handler.InputHandlerMixin._context_menu_owner_is_current
    )
    _trigger_owned_context_command = (
        input_handler.InputHandlerMixin._trigger_owned_context_command
    )
    _trigger_context_command = input_handler.InputHandlerMixin._trigger_context_command
    _add_context_command = input_handler.InputHandlerMixin._add_context_command
    _plan_item_edit_actions_enabled = (
        input_handler.InputHandlerMixin._plan_item_edit_actions_enabled
    )
    _context_annotations_are_current = (
        input_handler.InputHandlerMixin._context_annotations_are_current
    )
    _select_context_annotation_color = (
        input_handler.InputHandlerMixin._select_context_annotation_color
    )
    _apply_context_annotation_width = (
        input_handler.InputHandlerMixin._apply_context_annotation_width
    )

    def __init__(self, parent):
        super().__init__(parent)
        self._current_bid_ref = None
        self._current_page = None
        self._selected_uids = set()
        self._current_annotations = {}
        self._is_cleaning_up = False
        self.commands = []
        self._context_menu_command_trigger = self.commands.append
        self._context_menu_action_state = lambda _key: {"enabled": True}


class PlanNativeContextMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_top_level_menu_cannot_dispatch_after_plan_native_deletion(self):
        window = QtWidgets.QMainWindow()
        self.addCleanup(window.deleteLater)
        view = _OwnedPlanMenuHarness(window)
        menu = QtWidgets.QMenu(view.window())
        view._add_context_command(menu, "Paste", "paste")
        view.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(
            view, QtCore.QEvent.Type.DeferredDelete
        )
        self.assertFalse(isValid(view))
        self.assertTrue(isValid(menu))
        menu.actions()[0].trigger()
        self.assertEqual(view.commands, [])

    def test_empty_plan_menu_cannot_dispatch_after_cleanup_started(self):
        window = QtWidgets.QMainWindow()
        self.addCleanup(window.deleteLater)
        view = _OwnedPlanMenuHarness(window)
        menu = QtWidgets.QMenu(view.window())
        view._add_context_command(menu, "Paste", "paste")
        view._is_cleaning_up = True
        menu.actions()[0].trigger()
        self.assertEqual(view.commands, [])

    def test_annotation_menu_validates_native_owner_before_querying_action_state(self):
        window = QtWidgets.QMainWindow()
        self.addCleanup(window.deleteLater)
        view = _OwnedPlanMenuHarness(window)
        view._selected_uids = {"annotation"}
        view._current_annotations = {"annotation": object()}
        owner = view._context_menu_owner()
        view._context_menu_action_state = lambda _key: {"enabled": view.isEnabled()}
        view.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(
            view, QtCore.QEvent.Type.DeferredDelete
        )
        view._select_context_annotation_color(owner, view._current_annotations)
        view._apply_context_annotation_width(owner, view._current_annotations, 2.0)
        self.assertEqual(view.commands, [])

    def test_menu_cannot_dispatch_when_plan_is_deleted_during_exec(self):
        window = QtWidgets.QMainWindow()
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        view = _OwnedPlanMenuHarness(window)
        window.show()

        def create_menu(parent):
            menu = QtWidgets.QMenu(parent)

            def delete_plan_then_trigger():
                view.deleteLater()
                QtCore.QCoreApplication.sendPostedEvents(
                    view, QtCore.QEvent.Type.DeferredDelete
                )
                menu.actions()[1].trigger()
                menu.close()

            QtCore.QTimer.singleShot(0, delete_plan_then_trigger)
            return menu

        from types import SimpleNamespace

        event = SimpleNamespace(
            globalPos=lambda: window.mapToGlobal(QtCore.QPoint(20, 20))
        )
        with patch.object(input_handler, "QMenu", create_menu):
            view._show_common_context_menu(
                event, lambda menu: view._add_context_command(menu, "Paste", "paste")
            )
        self.assertFalse(isValid(view))
        self.assertEqual(view.commands, [])

    def test_main_and_detached_plan_menu_flows_keep_their_own_window(self):
        from tests import test_plan_view_ctrl_drag as helpers

        builder = helpers.CtrlDragTests()
        for window_type in (QtWidgets.QMainWindow, QtWidgets.QWidget):
            window = window_type()
            self.addCleanup(window.deleteLater)
            for selection in ("empty", "takeoff", "annotation"):
                with self.subTest(
                    window_type=window_type.__name__, selection=selection
                ):
                    if selection == "annotation":
                        view, _annotation = builder._make_annotation_control_point_view(
                            "rect"
                        )
                    else:
                        view = builder._make_area_control_point_view(
                            {"area1", "linear1"} if selection == "takeoff" else set()
                        )
                    view.window = lambda: window
                    menus = []

                    def create_menu(parent):
                        menu = QtWidgets.QMenu(parent)
                        menus.append(menu)
                        QtCore.QTimer.singleShot(0, menu.close)
                        return menu

                    with patch.object(input_handler, "QMenu", create_menu):
                        view.contextMenuEvent(helpers.FakeContextMenuEvent(-100, -100))
                    self.assertIs(menus[0].parentWidget(), window)
                    QtCore.QCoreApplication.sendPostedEvents(
                        menus[0], QtCore.QEvent.Type.DeferredDelete
                    )
                    self.assertFalse(isValid(menus[0]))

    def test_page_or_selection_change_invalidates_menu_command(self):
        window = QtWidgets.QWidget()
        self.addCleanup(window.deleteLater)
        view = _OwnedPlanMenuHarness(window)
        for change in ("page", "selection"):
            menu = QtWidgets.QMenu(window)
            view._add_context_command(menu, "Paste", "paste")
            if change == "page":
                view._current_page = object()
            else:
                view._selected_uids = {"different"}
            menu.actions()[0].trigger()
        self.assertEqual(view.commands, [])

    def test_top_level_owner_deletion_unwinds_native_menu(self):
        from types import SimpleNamespace

        window = QtWidgets.QWidget()
        view = _OwnedPlanMenuHarness(window)
        window.show()
        menus = []

        def create_menu(parent):
            menu = QtWidgets.QMenu(parent)
            menus.append(menu)

            def delete_window():
                window.deleteLater()
                QtCore.QCoreApplication.sendPostedEvents(
                    window, QtCore.QEvent.Type.DeferredDelete
                )

            QtCore.QTimer.singleShot(0, delete_window)
            return menu

        event = SimpleNamespace(
            globalPos=lambda: window.mapToGlobal(QtCore.QPoint(20, 20))
        )
        with patch.object(input_handler, "QMenu", create_menu):
            view._show_common_context_menu(
                event, lambda menu: view._add_context_command(menu, "Paste", "paste")
            )
        self.assertFalse(isValid(window))
        self.assertFalse(isValid(view))
        self.assertFalse(isValid(menus[0]))
        self.assertEqual(view.commands, [])

    def test_plan_menu_uses_top_level_owner_under_native_stack(self):
        window = QtWidgets.QMainWindow()
        self.addCleanup(window.close)
        self.addCleanup(window.deleteLater)
        stack = QtWidgets.QStackedWidget(window)
        window.setCentralWidget(stack)
        stack.setAttribute(QtCore.Qt.WidgetAttribute.WA_NativeWindow)
        view = _PlanMenuHarness()
        stack.addWidget(view)
        window.show()
        messages = []
        menus = []
        previous = QtCore.qInstallMessageHandler(
            lambda _kind, _context, message: messages.append(message)
        )
        self.addCleanup(QtCore.qInstallMessageHandler, previous)

        def create_menu(parent):
            menu = QtWidgets.QMenu(parent)
            menus.append(menu)
            QtCore.QTimer.singleShot(0, menu.close)
            return menu

        class Event:
            def globalPos(self):
                return window.mapToGlobal(QtCore.QPoint(20, 20))

        with patch.object(input_handler, "QMenu", create_menu):
            view._show_common_context_menu(
                Event(), lambda menu: menu.addAction("Paste")
            )
        self.assertIs(menus[0].parentWidget(), window)
        self.assertFalse(
            [message for message in messages if "must be a top level window" in message]
        )
