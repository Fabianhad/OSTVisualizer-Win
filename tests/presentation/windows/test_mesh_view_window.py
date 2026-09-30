import unittest
from types import SimpleNamespace
from ost_visualizer.presentation.windows.mesh_view_window import MeshViewWindow
from ost_visualizer.presentation.components.popup_tracking_combo import (
    PopupTrackingComboBox,
    parse_zoom_percent,
    update_zoom_combo,
)
from PySide6 import QtCore, QtGui, QtTest, QtWidgets


class MeshViewWindowCleanupTests(unittest.TestCase):
    def test_mesh_window_cleanup_clears_external_callback_references(self):
        window = MeshViewWindow.__new__(MeshViewWindow)
        retained = object()
        cleanup_calls = []
        window._is_closing = False
        window._resize_timer = SimpleNamespace(
            stop=lambda: cleanup_calls.append("timer-stop"),
            timeout=SimpleNamespace(disconnect=lambda _callback: None),
            deleteLater=lambda: cleanup_calls.append("timer-delete"),
        )
        window.viewer = SimpleNamespace(
            blockSignals=lambda _blocked: cleanup_calls.append("viewer-block"),
            cleanup=lambda: cleanup_calls.append("viewer-cleanup"),
        )
        window._zoom_combo = retained
        window._context_menu_command_trigger = lambda _key: retained
        window._context_menu_action_state = lambda: retained
        window.icon_provider = retained
        window._color_service = retained
        MeshViewWindow.cleanup(window)
        self.assertIsNone(window._zoom_combo)
        self.assertIsNone(window._context_menu_command_trigger)
        self.assertIsNone(window._context_menu_action_state)
        self.assertIsNone(window.icon_provider)
        self.assertIsNone(window._color_service)
        self.assertEqual(
            cleanup_calls,
            ["timer-stop", "timer-delete", "viewer-block", "viewer-cleanup"],
        )

    def test_mesh_window_cleanup_continues_after_resource_failures(self):
        window = MeshViewWindow.__new__(MeshViewWindow)
        retained = object()
        cleanup_calls = []

        def fail_timer_stop():
            cleanup_calls.append("timer-stop")
            raise RuntimeError("timer stop failed")

        def fail_viewer_block(_blocked):
            cleanup_calls.append("viewer-block")
            raise RuntimeError("viewer already deleted")

        def fail_viewer_cleanup():
            cleanup_calls.append("viewer-cleanup")
            raise RuntimeError("viewer cleanup failed")

        window._is_closing = False
        window._resize_timer = SimpleNamespace(
            stop=fail_timer_stop,
            timeout=SimpleNamespace(disconnect=lambda _callback: None),
            deleteLater=lambda: cleanup_calls.append("timer-delete"),
        )
        window.viewer = SimpleNamespace(
            blockSignals=fail_viewer_block,
            cleanup=fail_viewer_cleanup,
        )
        window._zoom_combo = retained
        window._context_menu_command_trigger = lambda _key: retained
        window._context_menu_action_state = lambda: retained
        window.icon_provider = retained
        window._color_service = retained
        with self.assertLogs(
            "ost_visualizer.presentation.windows.mesh_view_window",
            level="ERROR",
        ) as captured:
            MeshViewWindow.cleanup(window)
        self.assertIsNone(window._resize_timer)
        self.assertIsNone(window.viewer)
        self.assertIsNone(window._zoom_combo)
        self.assertIsNone(window._context_menu_command_trigger)
        self.assertIsNone(window._context_menu_action_state)
        self.assertIsNone(window.icon_provider)
        self.assertIsNone(window._color_service)
        self.assertEqual(
            cleanup_calls,
            ["timer-stop", "timer-delete", "viewer-block", "viewer-cleanup"],
        )
        self.assertEqual(len(captured.records), 3)


class MeshWindowZoomEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_detached_mesh_invalid_zoom_text_restores_current_zoom(self):
        combo = PopupTrackingComboBox()
        combo.setEditable(True)
        combo.setEditText("inf")
        zoom_writes = []
        window = MeshViewWindow.__new__(MeshViewWindow)
        window._zoom_combo = combo
        window.viewer = SimpleNamespace(
            get_zoom_percent=lambda: 250.0,
            set_zoom_percent=zoom_writes.append,
        )
        MeshViewWindow._on_zoom_text_entered(window)
        self.assertEqual(zoom_writes, [])
        self.assertEqual(combo.currentText(), "250%")

    def test_detached_mesh_ignored_tiny_zoom_displays_actual_zoom(self):
        combo = PopupTrackingComboBox()
        combo.setEditable(True)
        combo.setEditText("0.0000001")
        zoom_writes = []
        window = MeshViewWindow.__new__(MeshViewWindow)
        window._zoom_combo = combo
        window.viewer = SimpleNamespace(
            get_zoom_percent=lambda: 250.0,
            set_zoom_percent=zoom_writes.append,
        )
        MeshViewWindow._on_zoom_text_entered(window)
        self.assertEqual(zoom_writes, [0.0000001])
        self.assertEqual(combo.currentText(), "250%")

    def test_detached_mesh_ignored_zoom_button_displays_actual_zoom(self):
        combo = PopupTrackingComboBox()
        combo.setEditable(True)
        zoom_writes = []
        window = MeshViewWindow.__new__(MeshViewWindow)
        window._zoom_combo = combo
        window.viewer = SimpleNamespace(
            get_zoom_percent=lambda: 250.0,
            set_zoom_percent=zoom_writes.append,
        )
        MeshViewWindow._on_zoom_in(window)
        self.assertEqual(zoom_writes, [287.5])
        self.assertEqual(combo.currentText(), "250%")
