import os
import time
import unittest
from collections import deque
from types import SimpleNamespace
from unittest import mock
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import delete, isValid
from ost_visualizer.domain.aggregates.workspace_state_aggregate import (
    WorkspaceStateAggregate,
)
from ost_visualizer.domain.entities.workspace_state import WorkspaceState
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.components.project_tree_view import ProjectView
from ost_visualizer.presentation.utils.windows import (
    PersistentDialogWindowState,
    remove_minimize,
    remove_minimize_maximize,
    set_initial_window_size,
)
import tests.presentation.components.test_project_tree_view as project_fixture
from tests.helpers.workspace_state import InMemoryWorkspaceStateRepository
from tests.integration.cursor.cursor_trace_support import (
    _CursorTrace as _cursor_trace_support__CursorTrace,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.utils.windows import set_fixed_width_auto_height
from PySide6 import QtCore, QtWidgets
from tests.presentation.utils.dialog_lifecycle_support import (
    _app as _dialog_lifecycle_support__app,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class WindowButtonNativeOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.original_style = self.app.style().objectName()
        self.original_position = QtGui.QCursor.pos()
        self.windows = []
        self.traced_widgets = []
        self.trace = _cursor_trace_support__CursorTrace()

    def tearDown(self):
        for widget in self.traced_widgets:
            if isValid(widget):
                widget.removeEventFilter(self.trace)
        for window in self.windows:
            if isValid(window):
                window.close()
                delete(window)
        self.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.app.setStyle(self.original_style)
        if self.app.platformName() == "windows":
            QtGui.QCursor.setPos(self.original_position)

    def _host(self):
        window = QtWidgets.QWidget()
        self.windows.append(window)
        layout = QtWidgets.QVBoxLayout(window)
        tabs = QtWidgets.QTabWidget()
        layout.addWidget(tabs)
        projects = ProjectView(None, EventBus())
        projects.set_ui_access_manager(
            SimpleNamespace(can_edit_project=lambda *_args: True)
        )
        projects.build_complete_structure(
            project_fixture.ProjectTreeViewExpansionTests()._loaded_file(["bid-1"])
        )
        projects.top_tree.expandAll()
        tabs.addTab(projects, "Projects")
        other = QtWidgets.QWidget()
        other_layout = QtWidgets.QVBoxLayout(other)
        text = QtWidgets.QLineEdit("Text control")
        other_layout.addWidget(text)
        tabs.addTab(other, "Other")
        button = QtWidgets.QPushButton("Unrelated button")
        layout.addWidget(button)
        window.resize(900, 600)
        window.show()
        window.activateWindow()
        self.app.processEvents()
        return window, tabs, projects, text, button

    def _assert_no_promotion(self, widgets):
        for widget in widgets:
            self.assertFalse(
                widget.testAttribute(QtCore.Qt.WidgetAttribute.WA_NativeWindow),
                (widget.metaObject().className(), list(self.trace.records)),
            )
        self.assertIsNone(self.app.overrideCursor())

    def test_window_button_helpers_preserve_parent_and_sibling_native_ownership(self):
        for helper in (remove_minimize, remove_minimize_maximize):
            with self.subTest(helper=helper.__name__):
                window, tabs, projects, text, button = self._host()
                siblings = (window, tabs, projects, text, button)
                self._assert_no_promotion(siblings)
                dialog = QtWidgets.QDialog(window)
                helper(dialog)
                self.assertIsNone(dialog.windowHandle())
                self._assert_no_promotion(siblings)
                dialog.show()
                self.app.processEvents()
                handle = dialog.windowHandle()
                helper(dialog)
                self.assertIs(dialog.windowHandle(), handle)
                self._assert_no_promotion(siblings)
                self.assertFalse(
                    dialog.windowFlags() & QtCore.Qt.WindowType.WindowMinimizeButtonHint
                )
                maximize_hint = bool(
                    dialog.windowFlags() & QtCore.Qt.WindowType.WindowMaximizeButtonHint
                )
                self.assertEqual(maximize_hint, helper is remove_minimize)
                delete(dialog)

    def test_window_button_hints_are_not_changed_once_dialog_is_visible(self):
        for helper in (remove_minimize, remove_minimize_maximize):
            with self.subTest(helper=helper.__name__):
                dialog = QtWidgets.QDialog()
                self.windows.append(dialog)
                dialog.setWindowFlag(
                    QtCore.Qt.WindowType.WindowMinimizeButtonHint, True
                )
                dialog.setWindowFlag(
                    QtCore.Qt.WindowType.WindowMaximizeButtonHint, True
                )
                dialog.show()
                self.app.processEvents()
                helper(dialog)
                self.assertTrue(
                    dialog.windowFlags() & QtCore.Qt.WindowType.WindowMinimizeButtonHint
                )
                self.assertTrue(
                    dialog.windowFlags() & QtCore.Qt.WindowType.WindowMaximizeButtonHint
                )


class DialogLifecycleTests(unittest.TestCase):
    def test_fixed_width_auto_height_tracks_layout_spacing(self):
        _dialog_lifecycle_support__app()
        dialog = QtWidgets.QDialog()
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(QtWidgets.QLabel("First row"))
        layout.addWidget(QtWidgets.QLabel("Second row"))
        layout.setSpacing(5)
        set_fixed_width_auto_height(dialog, 240)
        compact_height = dialog.height()
        layout.setSpacing(25)
        set_fixed_width_auto_height(dialog, 240)
        try:
            self.assertEqual(dialog.width(), 240)
            self.assertEqual(dialog.minimumSize(), dialog.maximumSize())
            self.assertEqual(dialog.height(), compact_height + 20)
        finally:
            dialog.deleteLater()

    def test_fixed_width_auto_height_uses_height_for_width_of_wrapped_text(self):
        _dialog_lifecycle_support__app()
        dialog = QtWidgets.QDialog()
        layout = QtWidgets.QVBoxLayout(dialog)
        label = QtWidgets.QLabel("word " * 60)
        label.setWordWrap(True)
        layout.addWidget(label)
        try:
            set_fixed_width_auto_height(dialog, 120)
            narrow_height = dialog.height()
            set_fixed_width_auto_height(dialog, 600)
            wide_height = dialog.height()
            self.assertEqual(dialog.size(), QtCore.QSize(600, wide_height))
            self.assertGreater(narrow_height, wide_height)
        finally:
            dialog.deleteLater()

    def test_initial_window_size_sets_size_and_minimum(self):
        _dialog_lifecycle_support__app()
        widget = QtWidgets.QWidget()
        try:
            set_initial_window_size(widget, 320, 240)
            self.assertEqual(widget.size(), QtCore.QSize(320, 240))
            self.assertEqual(widget.minimumSize(), QtCore.QSize(320, 240))
            self.assertEqual(widget.maximumSize(), QtCore.QSize(16777215, 16777215))
        finally:
            widget.deleteLater()


class _CountingStateRepository(InMemoryWorkspaceStateRepository):
    def __init__(self):
        super().__init__(WorkspaceState())
        self.saves = 0

    def save(self, state):
        super().save(state)
        self.saves += 1


class PersistentDialogWindowStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _dialog_lifecycle_support__app()

    def setUp(self):
        self.repository = _CountingStateRepository()
        self.model = WorkspaceStateAggregate(self.repository)
        self.dialog = QtWidgets.QDialog()
        QtWidgets.QVBoxLayout(self.dialog).addWidget(QtWidgets.QLabel("Body"))
        self.addCleanup(self.dialog.deleteLater)

    def _state(self, **kwargs):
        self.window_state = PersistentDialogWindowState(
            self.dialog, self.model, "dlg", **kwargs
        )
        return self.window_state

    def test_saved_size_wins_over_default_size(self):
        state = self.model.state
        state.dialog_sizes["dlg"] = [410, 310]
        self.model.update_state(state)
        self._state(default_size=QtCore.QSize(500, 400))
        self.assertEqual(self.dialog.size(), QtCore.QSize(410, 310))

    def test_default_size_is_used_without_saved_size(self):
        self._state(default_size=QtCore.QSize(450, 350))
        self.assertEqual(self.dialog.size(), QtCore.QSize(450, 350))

    def test_size_is_bounded_by_minimum_hint_and_available_screen(self):
        self._state(default_size=QtCore.QSize(1, 1))
        minimum = self.dialog.minimumSizeHint()
        self.assertGreaterEqual(self.dialog.width(), minimum.width())
        self.assertGreaterEqual(self.dialog.height(), minimum.height())
        self.dialog.resize(10, 10)
        state = self.model.state
        state.dialog_sizes["dlg"] = [100000, 100000]
        self.model.update_state(state)
        self._state()
        screen = self.dialog.screen() or QtWidgets.QApplication.primaryScreen()
        available_size = screen.availableGeometry().size()
        self.assertEqual(self.dialog.size(), available_size)

    def test_dialog_keeps_close_and_maximize_but_not_minimize_buttons(self):
        self._state()
        flags = self.dialog.windowFlags()
        self.assertTrue(flags & QtCore.Qt.WindowType.WindowCloseButtonHint)
        self.assertTrue(flags & QtCore.Qt.WindowType.WindowMaximizeButtonHint)
        self.assertFalse(flags & QtCore.Qt.WindowType.WindowMinimizeButtonHint)

    def test_finished_persists_size_and_maximized_state_once(self):
        self._state(default_size=QtCore.QSize(450, 350))
        self.dialog.resize(380, 280)
        saves_before = self.repository.saves
        self.dialog.finished.emit(0)
        self.assertEqual(self.model.state.dialog_sizes["dlg"], [380, 280])
        self.assertFalse(self.model.state.dialog_maximized["dlg"])
        self.assertEqual(self.repository.saves, saves_before + 1)
        self.dialog.finished.emit(0)
        self.assertEqual(self.repository.saves, saves_before + 1)

    def test_workspace_write_failure_on_finish_is_ignored(self):
        self._state(default_size=QtCore.QSize(450, 350))
        with mock.patch.object(
            WorkspaceStateAggregate, "update_state", side_effect=OSError("disk")
        ):
            self.dialog.finished.emit(0)

    def test_saved_maximized_state_is_applied_once_on_show(self):
        state = self.model.state
        state.dialog_maximized["dlg"] = True
        self.model.update_state(state)
        window_state = self._state()
        with mock.patch.object(self.dialog, "showMaximized") as show_maximized:
            window_state.apply_show_state()
            window_state.apply_show_state()
        show_maximized.assert_called_once_with()

    def test_not_maximized_dialog_is_not_maximized_on_show(self):
        window_state = self._state()
        with mock.patch.object(self.dialog, "showMaximized") as show_maximized:
            window_state.apply_show_state()
        show_maximized.assert_not_called()
