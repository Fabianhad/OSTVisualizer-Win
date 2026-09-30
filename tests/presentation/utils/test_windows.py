import os
import time
import unittest
from collections import deque
from types import SimpleNamespace
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import delete, isValid
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.components.project_tree_view import ProjectView
from ost_visualizer.presentation.utils.windows import (
    remove_minimize,
    remove_minimize_maximize,
)
import tests.presentation.components.test_project_tree_view as project_fixture
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
                if helper is remove_minimize_maximize:
                    self.assertFalse(
                        dialog.windowFlags()
                        & QtCore.Qt.WindowType.WindowMaximizeButtonHint
                    )
                delete(dialog)


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
