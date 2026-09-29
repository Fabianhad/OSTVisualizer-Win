import ctypes
import os
import subprocess
import sys
import time
import unittest
from ctypes import wintypes
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest
from shiboken6 import delete, isValid
from ost_visualizer.presentation.dialogs.select_named_view_dialog import (
    SelectNamedViewDialog,
)
from ost_visualizer.presentation.modes.cursor import (
    CURSOR_MODE_ANNOTATION_PLACE,
    CURSOR_MODE_SELECT,
)
from ost_visualizer.presentation.utils import windows
from tests import test_dialog_cursor_ownership as cursor_fixture
from tests import test_plan_annotation_placement_keyboard as plan_fixture
from tests import test_plan_view_action_handler as action_fixture


class HotlinkCursorLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.host_fixture = cursor_fixture.DialogCursorOwnershipTests()
        self.host_fixture.app = self.app
        self.host_fixture.setUp()
        self.addCleanup(self.host_fixture.tearDown)
        self.qt_errors = []
        hook = patch(
            "sys.excepthook", side_effect=lambda *args: self.qt_errors.append(args)
        )
        hook.start()
        self.addCleanup(hook.stop)
        self.addCleanup(lambda: self.assertEqual(self.qt_errors, []))

    def _workflow(self):
        host = self.host_fixture._host()
        window, tabs, _projects, _text, _button = host
        plan = plan_fixture.TakeoffPlanView(
            color_service=plan_fixture.FakeColorService(),
            rendering_service=plan_fixture.FakeRenderingService(),
            load_coordinator=plan_fixture.FakeLoadCoordinator(),
            takeoff_renderer=plan_fixture.FakeTakeoffRenderer(),
            annotation_renderer=plan_fixture.FakeAnnotationRenderer(),
            linear_geometry=plan_fixture.FakeLinearGeometry(),
        )
        tabs.addTab(plan, "Plan")
        window.move(
            self.app.primaryScreen().availableGeometry().center()
            - window.rect().center()
        )
        plan.set_editing_enabled(True)
        plan.set_selection_enabled(True)
        plan._current_bid_page_uid = "p1"
        plan.setSceneRect(0, 0, 2000, 2000)
        data = action_fixture.FakeProjectData()
        data.annotations = [action_fixture._named_view_annotation("nv1", "Lobby")]
        writer = action_fixture.FakeAnnotationWriteService()
        undo = action_fixture.FakeUndoService()
        handler = action_fixture.PlanViewActionHandler(
            plan_view=plan,
            ui_state_manager=action_fixture.FakeUiState(),
            project_data_svc=data,
            project_write_svc=action_fixture.FakeWriteService(),
            annotation_write_svc=writer,
            page_settings_bar=action_fixture.FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=action_fixture.FakeEventBus(),
            deferred_persistence_manager=action_fixture.FakeDeferredPersistence(),
            ui_access_manager=action_fixture.FakeAccess(
                {action_fixture.Feature.PLACE_ANNOTATIONS}
            ),
        )
        plan.hotlink_placement_requested.connect(handler.on_hotlink_placement_requested)
        return host, plan, handler, writer, undo

    def _picker_factory(self, plan, ending, dialogs):
        def create(choices, parent=None):
            # The historical fix must cancel the real Plan before construction,
            # not merely emit a request to an external cursor controller.
            self.assertEqual(plan._cursor_mode, CURSOR_MODE_SELECT)
            self.assertIsNone(plan._annotation_place_type)
            time.sleep(0.025)
            dialog = SelectNamedViewDialog(choices, parent)
            dialogs.append(dialog)
            self.assertIsNone(dialog.windowHandle())
            self.assertFalse(
                dialog.windowFlags()
                & (
                    QtCore.Qt.WindowType.WindowMinimizeButtonHint
                    | QtCore.Qt.WindowType.WindowMaximizeButtonHint
                )
            )
            if ending == "save":
                callback = dialog.accept
            elif ending == "new":
                dialog._new_radio.setChecked(True)
                callback = dialog.accept
            elif ending == "destroy":
                callback = dialog.deleteLater
            elif ending == "destroy_owner":
                callback = plan.deleteLater
            else:
                callback = dialog.reject
            QtCore.QTimer.singleShot(20, dialog, callback)
            return dialog

        return create

    def test_real_plan_click_save_cancel_repeat_and_history(self):
        host, plan, handler, writer, undo = self._workflow()
        window, tabs, projects, text, button = host
        tabs.setCurrentWidget(plan)
        self.app.processEvents()
        for index, ending in enumerate(("save", "cancel", "save", "cancel", "new")):
            with self.subTest(ending=ending):
                writer.next_uids = [f"hotlink-{index}"]
                dialogs = []
                previous_writes = len(writer.insert_calls)
                self.assertTrue(plan.activate_annotation_placement("hotlink"))
                with patch.object(
                    action_fixture.handler_module,
                    "SelectNamedViewDialog",
                    self._picker_factory(plan, ending, dialogs),
                ):
                    QTest.mouseClick(
                        plan.viewport(),
                        QtCore.Qt.MouseButton.LeftButton,
                        pos=QtCore.QPoint(100, 100),
                    )
                self.assertEqual(len(dialogs), 1)
                self.assertEqual(
                    len(writer.insert_calls), previous_writes + (ending == "save")
                )
                if ending == "save":
                    self.assertEqual(plan._annotation_place_type, "hotlink")
                    spec = writer.insert_calls[-1][2][0]
                    self.assertEqual(spec.properties, {"BidPageViewUID": "nv1"})
                    self.assertEqual(spec.page_uid, "p1")
                    self.assertTrue(undo.undo())
                    self.assertTrue(undo.redo())
                    self.assertEqual(
                        writer.insert_calls[-1][2][0].properties, spec.properties
                    )
                elif ending == "new":
                    self.assertEqual(plan._annotation_place_type, "namedview")
                else:
                    self.assertEqual(plan._cursor_mode, CURSOR_MODE_SELECT)
                    self.assertIsNone(plan._annotation_place_type)
                self.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
                self.assertFalse(isValid(dialogs[0]))
                self.host_fixture._assert_no_promotion(
                    (window, tabs, projects, text, button, plan)
                )
                self.assertEqual(
                    button.cursor().shape(), QtCore.Qt.CursorShape.ArrowCursor
                )

    def test_destroyed_picker_or_owner_drops_completion_without_write(self):
        for ending in ("destroy", "destroy_owner"):
            with self.subTest(ending=ending):
                host, plan, handler, writer, undo = self._workflow()
                plan.activate_annotation_placement("hotlink")
                dialogs = []
                with patch.object(
                    action_fixture.handler_module,
                    "SelectNamedViewDialog",
                    self._picker_factory(plan, ending, dialogs),
                ):
                    handler.on_hotlink_placement_requested([10, 20], "p1")
                self.assertEqual(writer.insert_calls, [])
                self.assertEqual(undo.count, 0)
                self.assertFalse(isValid(dialogs[0]))
                self.host_fixture._assert_no_promotion(host)

    def test_initialization_exception_leaves_selection_mode_and_no_native_promotion(
        self,
    ):
        host, plan, handler, writer, undo = self._workflow()
        plan.activate_annotation_placement("hotlink")

        def fail_build(_dialog):
            raise RuntimeError("injected initialization failure")

        with patch.object(
            SelectNamedViewDialog,
            "_build_ui",
            fail_build,
        ), self.assertRaisesRegex(RuntimeError, "injected initialization failure"):
            handler.on_hotlink_placement_requested([10, 20], "p1")
        self.assertEqual(plan._cursor_mode, CURSOR_MODE_SELECT)
        self.assertIsNone(plan._annotation_place_type)
        self.assertEqual(writer.insert_calls, [])
        self.assertEqual(undo.count, 0)
        self.host_fixture._assert_no_promotion((*host, plan))

    def test_native_current_picker_does_not_leak(self):
        self._native_cycles(reconstruct_legacy=False)

    def test_native_legacy_helper_reproduces_despite_placement_cancellation(self):
        if self.app.platformName() != "windows":
            self.skipTest("Requires the Windows platform and native cursor handles")
        # Keep deliberate cursor corruption in its own process, separate from
        # current-workflow assertions and other Qt tests.
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from tests.test_hotlink_cursor_lifecycle import HotlinkCursorLifecycleTests as T; "
                "T.setUpClass(); t=T(); t.setUp(); "
                "t._native_cycles(reconstruct_legacy=True); "
                "raise SystemExit(not t.doCleanups())",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "QT_QPA_PLATFORM": "windows"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def _native_cycles(self, *, reconstruct_legacy):
        if self.app.platformName() != "windows":
            self.skipTest("Requires the Windows platform and native cursor handles")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetCursor.restype = wintypes.HANDLE
        user32.LoadCursorW.argtypes = (wintypes.HINSTANCE, ctypes.c_void_p)
        user32.LoadCursorW.restype = wintypes.HANDLE
        arrow = user32.LoadCursorW(None, 32512)
        ibeam = user32.LoadCursorW(None, 32513)

        def hover(widget):
            # A newly activated tab may still have its hidden-page geometry.
            self.app.processEvents()
            QtGui.QCursor.setPos(widget.mapToGlobal(widget.rect().center()))
            QTest.qWait(100)
            self.host_fixture.trace.record(widget, "hotlink-native-hover")
            self.assertIsNone(self.app.overrideCursor())
            return user32.GetCursor()

        safe_native_update = windows._remove_windows_style_bits

        def legacy_native_update(widget, bits):
            # Reconstruct the shared helper used even AFTER the old Hotlink
            # placement fix. Never install this behavior in production.
            widget.winId()
            safe_native_update(widget, bits)

        available = {name.lower(): name for name in QtWidgets.QStyleFactory.keys()}
        for style in ("fusion", "windowsvista", "windows11"):
            if style not in available:
                continue
            for legacy in (reconstruct_legacy,):
                with self.subTest(style=style, legacy=legacy):
                    self.app.setStyle(available[style])
                    host, plan, handler, writer, undo = self._workflow()
                    window, tabs, projects, text, button = host
                    QTest.qWait(150)
                    for ending in (
                        ("cancel",) if legacy else ("cancel", "save", "cancel", "save")
                    ):
                        plan.activate_annotation_placement("hotlink")
                        tabs.setCurrentWidget(projects)
                        projects.schedule_rename("project-1", "C:/jobs/test.mdb")
                        QTest.qWait(30)
                        editor = projects.top_tree.viewport().focusWidget()
                        self.assertIsInstance(editor, QtWidgets.QLineEdit)
                        hover(button)
                        self.assertEqual(
                            hover(editor),
                            ibeam,
                            (
                                ending,
                                editor.isVisible(),
                                self.app.widgetAt(QtGui.QCursor.pos()),
                                list(self.host_fixture.trace.records),
                            ),
                        )

                        def create(choices, parent=None):
                            self.assertEqual(plan._cursor_mode, CURSOR_MODE_SELECT)
                            time.sleep(0.025)
                            dialog = SelectNamedViewDialog(choices, parent)
                            QtCore.QTimer.singleShot(
                                30,
                                dialog,
                                dialog.accept if ending == "save" else dialog.reject,
                            )
                            return dialog

                        with patch.object(
                            windows,
                            "_remove_windows_style_bits",
                            legacy_native_update if legacy else safe_native_update,
                        ), patch.object(
                            action_fixture.handler_module,
                            "SelectNamedViewDialog",
                            create,
                        ):
                            handler.on_hotlink_placement_requested([10, 20], "p1")
                        self.app.sendPostedEvents(
                            None, QtCore.QEvent.Type.DeferredDelete
                        )
                        self.assertEqual(
                            button.cursor().shape(), QtCore.Qt.CursorShape.ArrowCursor
                        )
                        self.assertEqual(
                            hover(button),
                            ibeam if legacy else arrow,
                            list(self.host_fixture.trace.records),
                        )
                        self.assertEqual(
                            button.testAttribute(
                                QtCore.Qt.WidgetAttribute.WA_NativeWindow
                            ),
                            legacy,
                        )
                        if not legacy:
                            self.assertEqual(hover(projects.top_tree.viewport()), arrow)
                            self.assertEqual(hover(tabs.tabBar()), arrow)
                            tabs.setCurrentIndex(1)
                            self.assertEqual(hover(text), ibeam)
                            button.setFocus()
                            self.assertEqual(hover(button), arrow)
                            tabs.setCurrentWidget(plan)
                            self.assertNotEqual(hover(plan.viewport()), ibeam)
                            self.assertEqual(
                                plan._cursor_mode,
                                (
                                    CURSOR_MODE_ANNOTATION_PLACE
                                    if ending == "save"
                                    else CURSOR_MODE_SELECT
                                ),
                            )
                    window.close()
                    delete(window)
