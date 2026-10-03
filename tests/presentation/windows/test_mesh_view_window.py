import unittest
from types import SimpleNamespace
from ost_visualizer.presentation.actions.action_ids import (
    ACTION_RESET_VIEW,
    ACTION_UNDO,
    ACTION_ZOOM_IN,
)
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
        disconnected = []
        window._is_closing = False
        window._resize_timer = SimpleNamespace(
            stop=lambda: cleanup_calls.append("timer-stop"),
            timeout=SimpleNamespace(disconnect=disconnected.append),
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
        self.assertTrue(window._is_closing)
        self.assertIsNone(window._resize_timer)
        self.assertIsNone(window.viewer)
        self.assertIsNone(window._zoom_combo)
        self.assertIsNone(window._context_menu_command_trigger)
        self.assertIsNone(window._context_menu_action_state)
        self.assertIsNone(window.icon_provider)
        self.assertIsNone(window._color_service)
        self.assertEqual(
            [callback.__name__ for callback in disconnected], ["_on_resize_settled"]
        )
        self.assertIs(disconnected[0].__self__, window)
        self.assertEqual(
            cleanup_calls,
            ["timer-stop", "timer-delete", "viewer-block", "viewer-cleanup"],
        )
        # A second cleanup (for example from closeEvent) must not touch anything.
        MeshViewWindow.cleanup(window)
        self.assertEqual(len(cleanup_calls), 4)
        self.assertEqual(len(disconnected), 1)

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

        def already_disconnected(_callback):
            cleanup_calls.append("timer-disconnect")
            raise RuntimeError("signal already disconnected")

        window._is_closing = False
        window._resize_timer = SimpleNamespace(
            stop=fail_timer_stop,
            timeout=SimpleNamespace(disconnect=already_disconnected),
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
            [
                "timer-stop",
                "timer-disconnect",
                "timer-delete",
                "viewer-block",
                "viewer-cleanup",
            ],
        )
        # Only genuine failures are logged; an already-disconnected timer is not.
        self.assertEqual(
            [record.getMessage() for record in captured.records],
            [
                "Failed to stop the mesh-window resize timer",
                "Failed to block mesh-viewer signals during cleanup",
                "Failed to clean up the mesh viewer",
            ],
        )


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


class _ClampingZoomViewer:
    """Viewer double whose zoom clamps like the real one (10% to 400%)."""

    def __init__(self, zoom=250.0):
        self.zoom = zoom
        self.zoom_writes = []
        self.reset_calls = 0

    def get_zoom_percent(self):
        return self.zoom

    def set_zoom_percent(self, percent):
        self.zoom_writes.append(percent)
        self.zoom = min(400.0, max(10.0, percent))

    def reset_view(self):
        self.reset_calls += 1
        self.zoom = 100.0


class MeshWindowZoomControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def make_window(self, viewer):
        combo = PopupTrackingComboBox()
        combo.setEditable(True)
        for level in (100, 150, 250):
            combo.addItem(f"{level}%", level)
        window = MeshViewWindow.__new__(MeshViewWindow)
        window._zoom_combo = combo
        window.viewer = viewer
        window._popup_open = False
        return window, combo

    def test_detached_mesh_zoom_out_divides_by_zoom_factor_and_shows_actual_zoom(self):
        viewer = _ClampingZoomViewer(zoom=250.0)
        window, combo = self.make_window(viewer)
        MeshViewWindow._on_zoom_out(window)
        self.assertEqual(len(viewer.zoom_writes), 1)
        self.assertAlmostEqual(viewer.zoom_writes[0], 250.0 / 1.15, places=6)
        self.assertEqual(combo.currentText(), "217%")
        viewer.zoom = 10.0
        MeshViewWindow._on_zoom_out(window)
        # The field reports the clamped zoom, not the requested 8.7%.
        self.assertEqual(combo.currentText(), "10%")

    def test_detached_mesh_zoom_in_shows_clamped_actual_zoom(self):
        viewer = _ClampingZoomViewer(zoom=380.0)
        window, combo = self.make_window(viewer)
        MeshViewWindow._on_zoom_in(window)
        self.assertAlmostEqual(viewer.zoom_writes[0], 437.0, places=6)
        self.assertEqual(combo.currentText(), "400%")

    def test_detached_mesh_reset_view_displays_reset_zoom(self):
        viewer = _ClampingZoomViewer(zoom=250.0)
        window, combo = self.make_window(viewer)
        combo.setEditText("250%")
        MeshViewWindow._on_reset_view(window)
        self.assertEqual(viewer.reset_calls, 1)
        self.assertEqual(combo.currentText(), "100%")

    def test_detached_mesh_zoom_preset_applies_only_while_popup_is_open(self):
        viewer = _ClampingZoomViewer(zoom=250.0)
        window, combo = self.make_window(viewer)
        MeshViewWindow._on_zoom_combo_activated(window, 1)
        self.assertEqual(viewer.zoom_writes, [])
        window._popup_open = True
        MeshViewWindow._on_zoom_combo_activated(window, -1)
        self.assertEqual(viewer.zoom_writes, [])
        MeshViewWindow._on_zoom_combo_activated(window, 1)
        self.assertEqual(viewer.zoom_writes, [150.0])
        self.assertEqual(combo.currentText(), "150%")

    def test_detached_mesh_zoom_text_applies_valid_percentage(self):
        viewer = _ClampingZoomViewer(zoom=250.0)
        window, combo = self.make_window(viewer)
        combo.setEditText(" 500 % ")
        MeshViewWindow._on_zoom_text_entered(window)
        self.assertEqual(viewer.zoom_writes, [500.0])
        self.assertEqual(combo.currentText(), "400%")


class MeshWindowContextCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def make_window(self):
        window = MeshViewWindow.__new__(MeshViewWindow)
        window._is_closing = False
        triggered = []
        zoom_in = QtGui.QAction("Zoom In")
        zoom_in.triggered.connect(lambda: triggered.append("zoom_in"))
        reset = QtGui.QAction("Reset View")
        reset.setCheckable(True)
        reset.setChecked(True)
        reset.triggered.connect(lambda: triggered.append("reset"))
        window._camera_actions = {ACTION_ZOOM_IN: zoom_in, ACTION_RESET_VIEW: reset}
        window._context_menu_command_trigger = None
        window._context_menu_action_state = None
        self.addCleanup(zoom_in.deleteLater)
        self.addCleanup(reset.deleteLater)
        return window, triggered, zoom_in, reset

    def test_detached_mesh_context_state_reuses_toolbar_action_state(self):
        window, _triggered, zoom_in, _reset = self.make_window()
        self.assertEqual(
            MeshViewWindow._context_command_state(window, ACTION_ZOOM_IN),
            {
                "text": "Zoom In",
                "enabled": True,
                "checkable": False,
                "checked": False,
            },
        )
        zoom_in.setEnabled(False)
        self.assertFalse(
            MeshViewWindow._context_command_state(window, ACTION_ZOOM_IN)["enabled"]
        )
        self.assertEqual(
            MeshViewWindow._context_command_state(window, ACTION_RESET_VIEW),
            {
                "text": "Reset View",
                "enabled": True,
                "checkable": True,
                "checked": True,
            },
        )

    def test_detached_mesh_context_command_triggers_only_enabled_toolbar_action(self):
        window, triggered, zoom_in, _reset = self.make_window()
        MeshViewWindow._trigger_context_command(window, ACTION_ZOOM_IN)
        self.assertEqual(triggered, ["zoom_in"])
        zoom_in.setEnabled(False)
        MeshViewWindow._trigger_context_command(window, ACTION_ZOOM_IN)
        self.assertEqual(triggered, ["zoom_in"])

    def test_detached_mesh_context_commands_fall_back_to_external_handlers(self):
        window, triggered, _zoom_in, _reset = self.make_window()
        forwarded = []
        MeshViewWindow._trigger_context_command(window, ACTION_UNDO)
        self.assertEqual(MeshViewWindow._context_command_state(window, ACTION_UNDO), {})
        window._context_menu_command_trigger = forwarded.append
        window._context_menu_action_state = lambda key: {"enabled": key == ACTION_UNDO}
        MeshViewWindow._trigger_context_command(window, ACTION_UNDO)
        self.assertEqual(forwarded, [ACTION_UNDO])
        self.assertEqual(
            MeshViewWindow._context_command_state(window, ACTION_UNDO),
            {"enabled": True},
        )
        self.assertEqual(triggered, [])

    def test_detached_mesh_context_commands_are_inert_while_closing(self):
        window, triggered, _zoom_in, _reset = self.make_window()
        forwarded = []
        window._context_menu_command_trigger = forwarded.append
        window._is_closing = True
        MeshViewWindow._trigger_context_command(window, ACTION_ZOOM_IN)
        MeshViewWindow._trigger_context_command(window, ACTION_UNDO)
        self.assertEqual(triggered, [])
        self.assertEqual(forwarded, [])
        self.assertEqual(
            MeshViewWindow._context_command_state(window, ACTION_ZOOM_IN),
            {"enabled": False},
        )

    def test_detached_mesh_undo_redo_requests_follow_context_state(self):
        window, _triggered, _zoom_in, _reset = self.make_window()
        requests = []
        window.undo_requested = SimpleNamespace(emit=lambda: requests.append("undo"))
        window.redo_requested = SimpleNamespace(emit=lambda: requests.append("redo"))
        MeshViewWindow._request_undo(window)
        self.assertEqual(requests, [])
        window._context_menu_action_state = lambda key: {"enabled": key == ACTION_UNDO}
        MeshViewWindow._request_undo(window)
        MeshViewWindow._request_redo(window)
        self.assertEqual(requests, ["undo"])
        window._context_menu_action_state = lambda key: None
        MeshViewWindow._request_undo(window)
        self.assertEqual(requests, ["undo"])
