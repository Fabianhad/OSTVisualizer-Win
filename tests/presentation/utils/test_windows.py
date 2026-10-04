import ctypes
import gc
import os
import time
import unittest
from collections import deque
from types import SimpleNamespace
from unittest import mock
from unittest.mock import patch
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import delete, isValid
from ost_visualizer.domain.aggregates.workspace_state_aggregate import (
    WorkspaceStateAggregate,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.cover_sheet import JobStatus
from ost_visualizer.domain.entities.employee import PayClass
from ost_visualizer.domain.entities.font_definition import FontDefinition
from ost_visualizer.domain.entities.workspace_state import WorkspaceState
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.components.color_button import ColorButton
from ost_visualizer.presentation.components.project_tree_view import ProjectView
from ost_visualizer.presentation.dialogs.edit_condition_dialog import (
    EditConditionDialog,
)
from ost_visualizer.presentation.dialogs.employee_detail_dialog import (
    EmployeeDetailDialog,
)
from ost_visualizer.presentation.dialogs.options.font_dialog import FontDialog
from ost_visualizer.presentation.dialogs.set_scale_dialog import SetScaleDialog
from ost_visualizer.presentation.dtos.employee_edit_dtos import EmployeeRecord
from ost_visualizer.presentation.utils.windows import (
    PersistentDialogWindowState,
    remove_minimize,
    remove_minimize_maximize,
    set_initial_window_size,
)
import tests.presentation.components.test_project_tree_view as project_fixture
from tests.integration.conditions.test_nested_layer_editor import FakeReadService
from tests.presentation.dialogs.master_data_support import (
    FakeIconProvider as _master_data_support_FakeIconProvider,
    MasterJobStatusesDialog as _master_data_support_MasterJobStatusesDialog,
)
from tests.helpers.workspace_state import (
    InMemoryWorkspaceStateRepository,
    make_workspace_state_model,
    with_workspace_state,
)
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
        # Start from the opposite of every expectation so the controller is
        # what sets each hint rather than the QDialog defaults.
        self.dialog.setWindowFlag(QtCore.Qt.WindowType.WindowCloseButtonHint, False)
        self.dialog.setWindowFlag(QtCore.Qt.WindowType.WindowMinimizeButtonHint, True)
        self.dialog.setWindowFlag(QtCore.Qt.WindowType.WindowMaximizeButtonHint, False)
        flags = self.dialog.windowFlags()
        self.assertFalse(flags & QtCore.Qt.WindowType.WindowCloseButtonHint)
        self.assertTrue(flags & QtCore.Qt.WindowType.WindowMinimizeButtonHint)
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
        window_state = self._state(default_size=QtCore.QSize(450, 350))
        with mock.patch.object(
            WorkspaceStateAggregate, "update_state", side_effect=OSError("disk")
        ) as update_state:
            # Signal-delivered slot exceptions are swallowed by Qt bindings, so
            # call the slot directly to prove the OSError is handled.
            window_state._on_finished(0)
        update_state.assert_called_once()

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


_GWL_STYLE = -16
_WS_MINIMIZEBOX = 0x00020000
_WS_MAXIMIZEBOX = 0x00010000
_WS_SYSMENU = 0x00080000
_WS_CAPTION = 0x00C00000


def _native_style(widget: QtWidgets.QWidget) -> int:
    handle = widget.windowHandle()
    assert handle is not None, "dialog has no native window; was it shown?"
    return int(ctypes.windll.user32.GetWindowLongW(int(handle.winId()), _GWL_STYLE))


@unittest.skipUnless(os.name == "nt", "Native window styles exist only on Windows")
class WindowButtonNativeStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        if cls.app.platformName() != "windows":
            raise unittest.SkipTest(
                "Run with QT_QPA_PLATFORM=windows to inspect the real window style"
            )
        cls._quit_on_last_window_closed = cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "_quit_on_last_window_closed"):
            cls.app.setQuitOnLastWindowClosed(cls._quit_on_last_window_closed)

    def setUp(self):
        self.parent = QtWidgets.QWidget()
        self.parent.resize(300, 200)
        self.parent.show()
        self.app.processEvents()
        self.addCleanup(self._dispose, self.parent)

    def _dispose(self, widget):
        if isValid(widget):
            widget.close()
            delete(widget)
        self.app.processEvents()

    def _show(self, dialog):
        self.addCleanup(self._dispose, dialog)
        dialog.show()
        self.app.processEvents()
        return _native_style(dialog)

    def _assert_close_only(self, style, label=""):
        self.assertFalse(style & _WS_MINIMIZEBOX, f"{label} minimize button present")
        self.assertFalse(style & _WS_MAXIMIZEBOX, f"{label} maximize button present")
        self.assertEqual(style & (_WS_CAPTION | _WS_SYSMENU), _WS_CAPTION | _WS_SYSMENU)

    def _assert_maximize_only(self, style, label=""):
        self.assertFalse(style & _WS_MINIMIZEBOX, f"{label} minimize button present")
        self.assertTrue(style & _WS_MAXIMIZEBOX, f"{label} maximize button missing")
        self.assertEqual(style & (_WS_CAPTION | _WS_SYSMENU), _WS_CAPTION | _WS_SYSMENU)

    def _modal_dialog(self):
        dialog = QtWidgets.QDialog(self.parent)
        dialog.setModal(True)
        dialog.setFixedSize(240, 120)
        return dialog

    def test_default_dialog_has_both_buttons_so_the_probe_can_see_them(self):
        style = self._show(self._modal_dialog())
        self.assertTrue(style & _WS_MINIMIZEBOX)
        self.assertTrue(style & _WS_MAXIMIZEBOX)

    def test_remove_minimize_maximize_before_show_leaves_close_only(self):
        dialog = self._modal_dialog()
        remove_minimize_maximize(dialog)
        self.assertIsNone(dialog.windowHandle())
        self._assert_close_only(self._show(dialog))

    def test_resizable_dialog_loses_the_maximize_button_qt_would_add_back(self):
        dialog = QtWidgets.QDialog(self.parent)
        self.assertEqual(dialog.maximumSize(), QtCore.QSize(16777215, 16777215))
        remove_minimize_maximize(dialog)
        self._assert_close_only(self._show(dialog))
        dialog.hide()
        dialog.show()
        self.app.processEvents()
        self._assert_close_only(_native_style(dialog), "second show")

    def test_helper_called_twice_keeps_one_show_filter_with_latest_bits(self):
        dialog = QtWidgets.QDialog(self.parent)
        remove_minimize_maximize(dialog)
        remove_minimize(dialog)
        filters = [
            child
            for child in dialog.children()
            if child.objectName() == "windowButtonNativeStyle"
        ]
        self.assertEqual(len(filters), 1)
        self._assert_maximize_only(self._show(dialog))

    def test_remove_minimize_before_show_keeps_maximize_only(self):
        dialog = QtWidgets.QDialog(self.parent)
        remove_minimize(dialog)
        self._assert_maximize_only(self._show(dialog))

    def test_helper_before_show_does_not_create_native_windows(self):
        sibling = QtWidgets.QWidget(self.parent)
        dialog = QtWidgets.QDialog(self.parent)
        remove_minimize_maximize(dialog)
        self.assertIsNone(dialog.windowHandle())
        self.assertFalse(
            sibling.testAttribute(QtCore.Qt.WidgetAttribute.WA_NativeWindow)
        )
        self.assertFalse(
            self.parent.testAttribute(QtCore.Qt.WidgetAttribute.WA_NativeWindow)
        )
        self.assertIsNone(sibling.windowHandle())

    def test_buttons_stay_removed_after_hide_and_show(self):
        for helper, check in (
            (remove_minimize_maximize, self._assert_close_only),
            (remove_minimize, self._assert_maximize_only),
        ):
            with self.subTest(helper=helper.__name__):
                dialog = self._modal_dialog()
                helper(dialog)
                check(self._show(dialog), "first show")
                dialog.hide()
                self.app.processEvents()
                dialog.show()
                self.app.processEvents()
                check(_native_style(dialog), "second show")

    def test_buttons_stay_removed_after_reparenting_to_none(self):
        for helper, check in (
            (remove_minimize_maximize, self._assert_close_only),
            (remove_minimize, self._assert_maximize_only),
        ):
            with self.subTest(helper=helper.__name__):
                dialog = self._modal_dialog()
                helper(dialog)
                check(self._show(dialog), "parented")
                dialog.hide()
                dialog.setParent(None)
                dialog.show()
                self.app.processEvents()
                check(_native_style(dialog), "unparented")

    def test_show_filter_survives_python_garbage_collection(self):
        dialog = self._modal_dialog()
        remove_minimize_maximize(dialog)
        gc.collect()
        self._assert_close_only(self._show(dialog))

    def test_helper_after_show_still_clears_native_bits(self):
        dialog = self._modal_dialog()
        self._show(dialog)
        remove_minimize_maximize(dialog)
        self._assert_close_only(_native_style(dialog))

    def test_edit_condition_dialog_shows_only_the_close_button(self):
        dialog = with_workspace_state(EditConditionDialog)(
            None,
            None,
            Condition(uid="c1", name="Condition", ref_no=1),
            ["c1"],
            {"c1": Condition(uid="c1", name="Condition", ref_no=1)},
            {},
            {},
            lambda _uid: False,
            lambda _uid, _dto: True,
            read_service=FakeReadService(),
        )
        self.assertIsNone(dialog.windowHandle())
        self._assert_close_only(self._show(dialog))

    def test_setup_ui_dialog_shows_only_the_close_button(self):
        dialog = SetScaleDialog(None, self.parent, 1.0, 48.0, lambda _settings: True)
        self._assert_close_only(self._show(dialog))

    def test_init_dialog_shows_only_the_close_button(self):
        dialog = FontDialog(
            FontDefinition("Arial", "Bold", 12, 700, False, True), self.parent
        )
        self._assert_close_only(self._show(dialog))

    def test_color_dialog_loses_min_max_before_exec(self):
        seen = []

        def fake_exec(dialog):
            dialog.show()
            self.app.processEvents()
            seen.append(_native_style(dialog))
            dialog.close()
            return int(QtWidgets.QDialog.DialogCode.Rejected)

        button = ColorButton(QtGui.QColor("#336699"), parent=self.parent)
        with patch.object(QtWidgets.QColorDialog, "exec", fake_exec):
            button._choose_color()
        self.assertEqual(len(seen), 1)
        self._assert_close_only(seen[0])

    def test_input_dialog_loses_min_max_before_exec(self):
        dialog = QtWidgets.QInputDialog(self.parent)
        remove_minimize_maximize(dialog)
        self._assert_close_only(self._show(dialog))

    def test_persistent_state_dialog_keeps_maximize_but_not_minimize(self):
        dialog = _master_data_support_MasterJobStatusesDialog(
            _master_data_support_FakeIconProvider(),
            job_statuses=[
                JobStatus(uid="status-1", name="Bidding", locked=False, sequence=1)
            ],
            save_fn=lambda _changes: {},
            menu_mode=True,
        )
        self._assert_maximize_only(self._show(dialog))
        dialog.hide()
        dialog.show()
        self.app.processEvents()
        self._assert_maximize_only(_native_style(dialog), "second show")

    def test_show_event_dialog_shows_only_the_close_button(self):
        dialog = EmployeeDetailDialog(
            _master_data_support_FakeIconProvider(),
            [
                EmployeeRecord(
                    "1",
                    first_name="First",
                    last_name="One",
                    employee_no="1",
                    pay_class_uid="p",
                )
            ],
            0,
            make_workspace_state_model(),
            pay_classes=[PayClass("p", "Regular")],
        )
        self._assert_close_only(self._show(dialog))
        dialog.hide()
        dialog.show()
        self.app.processEvents()
        self._assert_close_only(_native_style(dialog), "second show")


class WindowButtonQtHintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _hints(self, helper):
        dialog = QtWidgets.QDialog()
        self.addCleanup(dialog.deleteLater)
        helper(dialog)
        self.assertIsNone(dialog.windowHandle())
        flags = dialog.windowFlags()
        return {
            name: bool(flags & getattr(QtCore.Qt.WindowType, name))
            for name in (
                "CustomizeWindowHint",
                "WindowTitleHint",
                "WindowSystemMenuHint",
                "WindowCloseButtonHint",
                "WindowMinimizeButtonHint",
                "WindowMaximizeButtonHint",
            )
        }

    def test_remove_minimize_maximize_sets_customized_close_only_hints(self):
        self.assertEqual(
            self._hints(remove_minimize_maximize),
            {
                "CustomizeWindowHint": True,
                "WindowTitleHint": True,
                "WindowSystemMenuHint": True,
                "WindowCloseButtonHint": True,
                "WindowMinimizeButtonHint": False,
                "WindowMaximizeButtonHint": False,
            },
        )

    def test_remove_minimize_sets_customized_hints_with_maximize_kept(self):
        self.assertEqual(
            self._hints(remove_minimize),
            {
                "CustomizeWindowHint": True,
                "WindowTitleHint": True,
                "WindowSystemMenuHint": True,
                "WindowCloseButtonHint": True,
                "WindowMinimizeButtonHint": False,
                "WindowMaximizeButtonHint": True,
            },
        )

    def test_hints_are_left_alone_on_a_visible_widget(self):
        dialog = QtWidgets.QDialog()
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        before = dialog.windowFlags()
        remove_minimize_maximize(dialog)
        self.assertEqual(dialog.windowFlags(), before)
        self.assertEqual(
            dialog.findChildren(QtCore.QObject, "windowButtonNativeStyle"), []
        )
        dialog.hide()
