import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from ost_visualizer.domain.entities.workspace_state import (
    DetachedWindowState,
    WorkspaceState,
)
from ost_visualizer.presentation.coordinators.workspace_state_coordinator import (
    WorkspaceStateCoordinator,
)
from ost_visualizer.presentation.windows.annotation_view_window import (
    AnnotationViewWindow,
)
from ost_visualizer.presentation.windows.view_window import ViewWindow
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import delete, isValid


class DetachedWindowRestoreLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def window(self, cls):
        # Use the real native window and shared restore lifecycle, with Page
        # delivery controlled explicitly instead of starting render workers.
        window = cls.__new__(cls)
        QtWidgets.QMainWindow.__init__(window)
        window.setCentralWidget(QtWidgets.QGraphicsView())
        window._is_closing = False
        window._pending_named_view_resize_focus = False
        window._initial_show_requested = False
        window._initial_page_geometry_ready = False
        window._show_timer = QtCore.QTimer(window)
        window.logger = logging.getLogger(__name__)
        window.view = None
        window.plan_view = None
        window._named_view_blank_canvas_active = False
        self.addCleanup(lambda: delete(window) if isValid(window) else None)
        return window

    def saved(self, mode):
        source = QtWidgets.QMainWindow()
        self.addCleanup(lambda: delete(source) if isValid(source) else None)
        source.setGeometry(100, 100, 550, 420)
        if mode == "maximized":
            source.showMaximized()
        elif mode == "fullscreen":
            source.showFullScreen()
        else:
            source.show()
        return DetachedWindowState(
            open=True,
            geometry_b64=WorkspaceStateCoordinator._encode_byte_array(
                source.saveGeometry()
            ),
            is_maximized=mode == "maximized",
            is_fullscreen=mode == "fullscreen",
        ), QtCore.QRect(source.normalGeometry())

    def prepare(self, window, saved):
        window.set_initial_window_state(
            WorkspaceStateCoordinator._decode_byte_array(saved.geometry_b64),
            saved.is_maximized,
            saved.is_fullscreen,
        )
        window.show_when_page_ready()
        self.assertFalse(window.isVisible())

    def track(self, window, key, saved):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        QtCore.QObject.__init__(coordinator)
        coordinator._cleaned_up = False
        coordinator._host_window = None
        coordinator._tracked_toolbars = ()
        coordinator._tracked_detached_windows = {key: window}
        coordinator._state = WorkspaceState()
        previous = coordinator._get_detached_window_state(key)
        previous.geometry_b64 = saved.geometry_b64
        previous.is_maximized = saved.is_maximized
        previous.is_fullscreen = saved.is_fullscreen
        coordinator.request_save = lambda: None
        window.installEventFilter(coordinator)
        self.addCleanup(lambda: delete(coordinator) if isValid(coordinator) else None)
        return coordinator

    def test_shutdown_hide_before_debounce_preserves_latest_user_geometry(self):
        for cls, key in (
            (AnnotationViewWindow, "annotation_view"),
            (ViewWindow, "view_window"),
        ):
            with self.subTest(window=cls.__name__):
                saved, _normal = self.saved("normal")
                window = self.window(cls)
                coordinator = self.track(window, key, saved)
                self.prepare(window, saved)
                window._on_page_geometry_ready()
                window.setGeometry(120, 130, 570, 440)
                latest = WorkspaceStateCoordinator._encode_byte_array(
                    window.saveGeometry()
                )
                # Main hides detached windows before draining writes and flushing
                # workspace state. No debounced save has run since the resize.
                window.hide()
                previous = coordinator._get_detached_window_state(key)
                captured = coordinator._capture_detached_window_state(
                    previous, window, True
                )
                self.assertEqual(captured.geometry_b64, latest)
                restored = self.window(cls)
                self.prepare(restored, captured)
                restored._on_page_geometry_ready()
                self.assertEqual(
                    restored.normalGeometry(), QtCore.QRect(120, 130, 570, 440)
                )

    def test_shutdown_hide_before_debounce_preserves_latest_window_state(self):
        for cls, key in (
            (AnnotationViewWindow, "annotation_view"),
            (ViewWindow, "view_window"),
        ):
            for mode in ("maximized", "fullscreen"):
                with self.subTest(window=cls.__name__, mode=mode):
                    saved, normal = self.saved("normal")
                    window = self.window(cls)
                    coordinator = self.track(window, key, saved)
                    self.prepare(window, saved)
                    window._on_page_geometry_ready()
                    if mode == "maximized":
                        window.showMaximized()
                    else:
                        window.showFullScreen()
                    window.hide()
                    captured = coordinator._capture_detached_window_state(
                        coordinator._get_detached_window_state(key), window, True
                    )
                    self.assertEqual(captured.is_maximized, mode == "maximized")
                    self.assertEqual(captured.is_fullscreen, mode == "fullscreen")
                    restored = self.window(cls)
                    self.prepare(restored, captured)
                    restored._on_page_geometry_ready()
                    self.assertEqual(restored.normalGeometry(), normal)

    def test_late_page_delivery_does_not_repeat_initial_show_after_shutdown_hide(self):
        for cls in (AnnotationViewWindow, ViewWindow):
            with self.subTest(window=cls.__name__):
                saved, _normal = self.saved("normal")
                window = self.window(cls)
                self.prepare(window, saved)
                window._on_show_timeout()
                window.setGeometry(120, 130, 570, 440)
                window.hide()
                window._on_page_geometry_ready()
                window._on_show_timeout()
                self.assertFalse(window.isVisible())
                self.assertEqual(
                    window.normalGeometry(), QtCore.QRect(120, 130, 570, 440)
                )

    def test_real_close_during_page_loading_keeps_saved_state_and_rejects_late_show(
        self,
    ):
        from tests.test_detached_window_workspace_state import (
            DetachedPageViewManagerLifecycleTests,
        )

        for cls, key in (
            (AnnotationViewWindow, "annotation_view"),
            (ViewWindow, "view_window"),
        ):
            with self.subTest(window=cls.__name__):
                saved, _normal = self.saved("fullscreen")
                window = DetachedPageViewManagerLifecycleTests._make_toolbar_window(
                    self, cls
                )
                self.addCleanup(
                    lambda window=window: delete(window) if isValid(window) else None
                )
                coordinator = self.track(window, key, saved)
                self.prepare(window, saved)
                window.close()
                self.assertTrue(window._is_closing)
                window._on_page_geometry_ready()
                window._on_show_timeout()
                self.assertFalse(window.isVisible())
                captured = coordinator._capture_detached_window_state(
                    coordinator._get_detached_window_state(key), window, True
                )
                self.assertEqual(captured, saved)

    def test_real_close_cleanup_keeps_final_visible_snapshot(self):
        from tests.test_detached_window_workspace_state import (
            DetachedPageViewManagerLifecycleTests,
        )

        for cls, key in (
            (AnnotationViewWindow, "annotation_view"),
            (ViewWindow, "view_window"),
        ):
            with self.subTest(window=cls.__name__):
                saved, _normal = self.saved("normal")
                window = DetachedPageViewManagerLifecycleTests._make_toolbar_window(
                    self, cls
                )
                self.addCleanup(
                    lambda window=window: delete(window) if isValid(window) else None
                )
                coordinator = self.track(window, key, saved)
                self.prepare(window, saved)
                window._on_page_geometry_ready()
                window.resize(window.width() + 40, window.height() + 30)
                latest = WorkspaceStateCoordinator._encode_byte_array(
                    window.saveGeometry()
                )
                window.close()
                self.assertTrue(window._is_closing)
                self.assertEqual(
                    coordinator._get_detached_window_state(key).geometry_b64, latest
                )

    def test_old_window_close_cannot_replace_new_window_snapshot(self):
        saved, _normal = self.saved("normal")
        old = self.window(AnnotationViewWindow)
        coordinator = self.track(old, "annotation_view", saved)
        self.prepare(old, saved)
        old._on_page_geometry_ready()
        current = self.window(AnnotationViewWindow)
        self.prepare(current, saved)
        current._on_page_geometry_ready()
        current.setGeometry(120, 130, 570, 440)
        coordinator._tracked_detached_windows["annotation_view"] = current
        current.installEventFilter(coordinator)
        coordinator.eventFilter(current, QtGui.QMoveEvent(current.pos(), current.pos()))
        latest = WorkspaceStateCoordinator._encode_byte_array(current.saveGeometry())
        coordinator.eventFilter(old, QtGui.QCloseEvent())
        self.assertEqual(
            coordinator._get_detached_window_state("annotation_view").geometry_b64,
            latest,
        )

    def test_save_while_page_is_loading_preserves_saved_geometry_and_state(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        for cls in (AnnotationViewWindow, ViewWindow):
            for mode in ("normal", "maximized", "fullscreen"):
                with self.subTest(window=cls.__name__, mode=mode):
                    saved, normal = self.saved(mode)
                    window = self.window(cls)
                    self.prepare(window, saved)
                    window.resize(20, 20)
                    captured = coordinator._capture_detached_window_state(
                        saved, window, True
                    )
                    self.assertEqual(captured, saved)
                    window._on_page_geometry_ready()
                    self.assertEqual(window.normalGeometry(), normal)

    def test_restore_preserves_normal_geometry_before_and_after_native_show(self):
        for cls in (AnnotationViewWindow, ViewWindow):
            for mode in ("normal", "maximized", "fullscreen"):
                for phase in ("geometry_ready", "timeout"):
                    with self.subTest(window=cls.__name__, mode=mode, phase=phase):
                        saved, normal = self.saved(mode)
                        window = self.window(cls)
                        self.prepare(window, saved)
                        if phase == "geometry_ready":
                            window._on_page_geometry_ready()
                        else:
                            window._on_show_timeout()
                        self.assertTrue(window.isVisible())
                        self.assertEqual(window.isMaximized(), saved.is_maximized)
                        self.assertEqual(window.isFullScreen(), saved.is_fullscreen)
                        self.assertEqual(window.normalGeometry(), normal)
                        window._on_page_geometry_ready()
                        self.assertEqual(window.normalGeometry(), normal)
                        window.showNormal()
                        self.assertEqual(window.geometry(), normal)

    def test_close_captures_latest_geometry_before_teardown_and_debounce(self):
        for cls, key in (
            (AnnotationViewWindow, "annotation_view"),
            (ViewWindow, "view_window"),
        ):
            with self.subTest(window=cls.__name__):
                saved, _normal = self.saved("normal")
                window = self.window(cls)
                self.prepare(window, saved)
                window._on_page_geometry_ready()
                window.setGeometry(120, 130, 570, 440)
                latest = WorkspaceStateCoordinator._encode_byte_array(
                    window.saveGeometry()
                )
                coordinator = WorkspaceStateCoordinator.__new__(
                    WorkspaceStateCoordinator
                )
                QtCore.QObject.__init__(coordinator)
                coordinator._cleaned_up = False
                coordinator._host_window = None
                coordinator._tracked_toolbars = ()
                coordinator._tracked_detached_windows = {key: window}
                coordinator._state = WorkspaceState()
                previous = coordinator._get_detached_window_state(key)
                previous.geometry_b64 = saved.geometry_b64
                coordinator.request_save = lambda: None
                coordinator.eventFilter(window, QtGui.QCloseEvent())
                self.assertEqual(
                    coordinator._get_detached_window_state(key).geometry_b64, latest
                )

    def test_virtual_monitors_and_repeated_restore_cycles(self):
        root = str(Path(__file__).resolve().parents[1])
        for second_x in (1920, -2560):
            for synchronous in (False, True):
                with self.subTest(second_x=second_x, synchronous=synchronous):
                    with tempfile.TemporaryDirectory() as directory:
                        config = {
                            "synchronousWindowSystemEvents": synchronous,
                            "windowFrameMargins": False,
                            "screens": [
                                {
                                    "name": "A",
                                    "x": 0,
                                    "y": 0,
                                    "width": 1920,
                                    "height": 1080,
                                },
                                {
                                    "name": "B",
                                    "x": second_x,
                                    "y": -200,
                                    "width": 2560,
                                    "height": 1440,
                                },
                            ],
                        }
                        Path(directory, "screens.json").write_text(json.dumps(config))
                        environment = dict(os.environ, PYTHONPATH=root)
                        result = subprocess.run(
                            [
                                sys.executable,
                                "-X",
                                "faulthandler",
                                "-c",
                                "from tests.test_detached_window_restore_lifecycle import run_monitor_probe; run_monitor_probe()",
                            ],
                            cwd=directory,
                            env=environment,
                            capture_output=True,
                            text=True,
                            timeout=30,
                        )
                        self.assertEqual(
                            result.returncode, 0, result.stdout + result.stderr
                        )
                        for missing in (False, True):
                            changed = dict(config)
                            changed["screens"] = [
                                dict(screen) for screen in config["screens"]
                            ]
                            if missing:
                                changed["screens"] = changed["screens"][:1]
                            else:
                                changed["screens"][1].update(
                                    x=-2560 if second_x > 0 else 1920, y=100
                                )
                            Path(directory, "screens.json").write_text(
                                json.dumps(changed)
                            )
                            result = subprocess.run(
                                [
                                    sys.executable,
                                    "-X",
                                    "faulthandler",
                                    "-c",
                                    "from tests.test_detached_window_restore_lifecycle import run_changed_screens_probe; run_changed_screens_probe()",
                                ],
                                cwd=directory,
                                env=environment,
                                capture_output=True,
                                text=True,
                                timeout=30,
                            )
                            self.assertEqual(
                                result.returncode, 0, result.stdout + result.stderr
                            )


def run_monitor_probe():
    from PySide6.QtTest import QSignalSpy, QTest

    app = QtWidgets.QApplication(
        ["restore-test", "-platform", "offscreen:configfile=screens.json"]
    )
    screens = app.screens()
    target = next(screen for screen in screens if screen.name() == "B")
    target_geometry = QtCore.QRect(target.geometry())
    test = DetachedWindowRestoreLifecycleTests()
    test.app = app
    coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
    snapshots = []
    try:
        for cls in (AnnotationViewWindow, ViewWindow):
            for mode in ("normal", "maximized", "fullscreen"):
                source = QtWidgets.QMainWindow()
                source.setScreen(
                    next(screen for screen in app.screens() if screen.name() == "B")
                )
                normal = QtCore.QRect(
                    target_geometry.topLeft() + QtCore.QPoint(100, 100),
                    QtCore.QSize(950, 650),
                )
                source.setGeometry(normal)
                if mode == "maximized":
                    source.showMaximized()
                elif mode == "fullscreen":
                    source.showFullScreen()
                else:
                    source.show()
                test.assertTrue(QTest.qWaitForWindowExposed(source))
                normal = QtCore.QRect(source.normalGeometry())
                saved = coordinator._capture_detached_window_state(
                    DetachedWindowState(), source, True
                )
                snapshots.append({"window": cls.__name__, "state": saved.to_dict()})
                delete(source)
                for phase in ("ready", "timeout", "ready"):
                    window = test.window(cls)
                    test.prepare(window, saved)
                    # Simulate a workspace save while render delivery is paused.
                    saved = coordinator._capture_detached_window_state(
                        saved, window, True
                    )
                    if phase == "ready":
                        window._on_page_geometry_ready()
                    else:
                        window._on_show_timeout()
                    test.assertTrue(QTest.qWaitForWindowExposed(window))
                    test.assertEqual(window.screen().name(), "B")
                    test.assertEqual(window.normalGeometry(), normal)
                    test.assertEqual(window.isMaximized(), mode == "maximized")
                    test.assertEqual(window.isFullScreen(), mode == "fullscreen")
                    test.assertTrue(target_geometry.contains(window.geometry()))
                    saved = coordinator._capture_detached_window_state(
                        saved, window, True
                    )
                    resized = QSignalSpy(window.windowHandle().widthChanged)
                    window.showNormal()
                    if window.geometry() != normal:
                        test.assertTrue(resized.wait(1000))
                    test.assertEqual(window.geometry(), normal)
                    delete(window)
    finally:
        test.doCleanups()
    Path("saved.json").write_text(json.dumps(snapshots))


def run_changed_screens_probe():
    from PySide6.QtTest import QTest

    app = QtWidgets.QApplication(
        ["restore-test", "-platform", "offscreen:configfile=screens.json"]
    )
    expected = "B" if len(app.screens()) > 1 else "A"
    test = DetachedWindowRestoreLifecycleTests()
    test.app = app
    classes = {"AnnotationViewWindow": AnnotationViewWindow, "ViewWindow": ViewWindow}
    try:
        for snapshot in json.loads(Path("saved.json").read_text()):
            saved = DetachedWindowState.from_dict(snapshot["state"])
            window = test.window(classes[snapshot["window"]])
            test.prepare(window, saved)
            window._on_page_geometry_ready()
            test.assertTrue(QTest.qWaitForWindowExposed(window))
            test.assertEqual(window.screen().name(), expected)
            test.assertTrue(window.screen().geometry().contains(window.geometry()))
            test.assertTrue(
                window.screen().geometry().contains(window.normalGeometry())
            )
            test.assertGreater(window.normalGeometry().width(), 100)
            test.assertGreater(window.normalGeometry().height(), 100)
            test.assertEqual(window.isMaximized(), saved.is_maximized)
            test.assertEqual(window.isFullScreen(), saved.is_fullscreen)
            delete(window)
    finally:
        test.doCleanups()


if __name__ == "__main__":
    unittest.main()
