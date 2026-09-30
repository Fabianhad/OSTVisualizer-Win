import ctypes
import os
import tempfile
import time
import unittest
from collections import deque
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest
from shiboken6 import delete, isValid
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.components.project_tree_view import ProjectView
from tests.presentation.dialogs.cover_sheet.path_support import (
    CoverSheetDialog,
    _FakeIconProvider,
    _ManualRunnablePool,
    _cover_sheet_data,
)
import tests.presentation.components.test_project_tree_view as project_fixture
from tests.integration.cursor.cursor_trace_support import (
    _CursorTrace as _cursor_trace_support__CursorTrace,
)


class DialogCursorOwnershipTests(unittest.TestCase):
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

    def test_failed_cover_sheet_initialization_does_not_change_cursor_ownership(self):
        window, tabs, projects, text, button = self._host()
        with patch(
            "ost_visualizer.presentation.utils.windows.PersistentDialogWindowState._bounded_size",
            side_effect=RuntimeError("injected initialization failure"),
        ), self.assertRaisesRegex(RuntimeError, "injected initialization failure"):
            CoverSheetDialog(_FakeIconProvider(), window, _cover_sheet_data())
        self._assert_no_promotion((window, tabs, projects, text, button))

    def test_pending_metadata_after_navigation_close_or_destruction_keeps_ownership(
        self,
    ):
        for ending in ("close", "destroy", "failure"):
            with self.subTest(
                ending=ending
            ), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "delayed.pdf"
                path.touch()
                window, tabs, projects, text, button = self._host()
                pool = _ManualRunnablePool()

                def metadata(_path):
                    if ending == "failure":
                        raise OSError("injected metadata failure")
                    return [(42.0, 30.0)]

                dialog = CoverSheetDialog(
                    _FakeIconProvider(),
                    window,
                    _cover_sheet_data(image_path=str(path)),
                    pdf_metadata_pool=pool,
                    pdf_page_sizes_fn=metadata,
                )
                dialog.show()
                self.app.processEvents()
                item = dialog.plan_tree.topLevelItem(0)
                delegate = dialog.plan_tree.itemDelegateForColumn(6)
                self.assertIsNone(
                    delegate.createEditor(
                        dialog.plan_tree.viewport(),
                        QtWidgets.QStyleOptionViewItem(),
                        dialog.plan_tree.indexFromItem(item, 6),
                    )
                )
                self.assertTrue(pool.runnables)
                tabs.setCurrentIndex(1)
                text.setFocus()
                button.setFocus()
                tabs.setCurrentIndex(0)
                projects.build_complete_structure([])
                if ending == "failure":
                    pool.run_next()
                if ending == "destroy":
                    dialog.deleteLater()
                    self.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
                    self.assertFalse(isValid(dialog))
                else:
                    dialog.reject()
                while pool.runnables:
                    pool.run_next()
                if isValid(dialog):
                    delete(dialog)
                self.app.processEvents()
                self._assert_no_promotion((window, tabs, projects, text, button))

    def test_native_cursor_recovers_after_delayed_cover_sheet_cycles(self):
        if self.app.platformName() != "windows":
            self.skipTest("Run with QT_QPA_PLATFORM=windows to inspect the real cursor")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetCursor.restype = wintypes.HANDLE
        user32.LoadCursorW.argtypes = (wintypes.HINSTANCE, ctypes.c_void_p)
        user32.LoadCursorW.restype = wintypes.HANDLE
        arrow = user32.LoadCursorW(None, 32512)
        ibeam = user32.LoadCursorW(None, 32513)

        def hover(widget, expected):
            QtGui.QCursor.setPos(widget.mapToGlobal(widget.rect().center()))
            QTest.qWait(100)
            self.trace.record(widget, "native-hover-settled")
            self.assertEqual(user32.GetCursor(), expected, list(self.trace.records))
            self.assertIsNone(self.app.overrideCursor())

        available = {name.lower(): name for name in QtWidgets.QStyleFactory.keys()}
        for style in ("fusion", "windowsvista", "windows11"):
            if style not in available:
                continue
            self.app.setStyle(available[style])
            window, tabs, projects, text, button = self._host()
            # Observe only these live hosts, not partially destructed dialog
            # children whose QWidget.window() is unsafe during teardown.
            for widget in (
                window,
                tabs.tabBar(),
                projects.top_tree.viewport(),
                text,
                button,
            ):
                widget.installEventFilter(self.trace)
                self.traced_widgets.append(widget)
            QTest.qWait(150)
            for cycle in range(3):
                with self.subTest(style=style, cycle=cycle):
                    projects.schedule_rename("project-1", "C:/jobs/test.mdb")
                    QTest.qWait(30)
                    editor = projects.top_tree.viewport().focusWidget()
                    self.assertIsInstance(editor, QtWidgets.QLineEdit)
                    hover(editor, ibeam)
                    # Hold construction at the proven timing boundary: the parent
                    # window is displaying its inline editor's I-beam cursor.
                    time.sleep(0.025)
                    dialog = CoverSheetDialog(
                        _FakeIconProvider(), window, _cover_sheet_data()
                    )
                    QtCore.QTimer.singleShot(50, dialog.reject)
                    dialog.exec()
                    delete(dialog)
                    hover(button, arrow)
                    hover(projects.top_tree.viewport(), arrow)
                    hover(tabs.tabBar(), arrow)
                    tabs.setCurrentIndex(1)
                    hover(text, ibeam)
                    text.setFocus()
                    button.setFocus()
                    hover(button, arrow)
                    tabs.setCurrentIndex(0)
            window.close()
