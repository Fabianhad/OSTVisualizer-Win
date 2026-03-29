import unittest
from types import SimpleNamespace
from PySide6 import QtCore
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.use_cases.annotation_view.open_annotation_view_use_case import (
    OpenAnnotationViewUseCase,
)
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.workspace_state import WorkspaceState
from ost_visualizer.presentation.coordinators.workspace_state_coordinator import (
    WorkspaceStateCoordinator,
)
from ost_visualizer.presentation.managers.detached_page_view_manager import (
    DetachedPageViewManager,
)


def _encoded_geometry(value: bytes = b"geometry") -> str:
    return bytes(QtCore.QByteArray(value).toBase64()).decode("ascii")


class FakeDetachedWindow:
    def __init__(
        self,
        *,
        visible: bool = True,
        maximized: bool = False,
        minimized: bool = False,
    ):
        self.visible = visible
        self.maximized = maximized
        self.minimized = minimized
        self.initial_states = []
        self.restored_geometries = []
        self.show_maximized_calls = 0
        self.show_normal_calls = 0
        self.dropdown_sizes = None
        self.raise_calls = 0
        self.activate_calls = 0

    def isVisible(self):
        return self.visible

    def set_initial_window_state(self, geometry, is_maximized):
        self.initial_states.append((bytes(geometry), is_maximized))

    def restoreGeometry(self, geometry):
        self.restored_geometries.append(bytes(geometry))

    def isMaximized(self):
        return self.maximized

    def isMinimized(self):
        return self.minimized

    def showMaximized(self):
        self.show_maximized_calls += 1
        self.maximized = True
        self.minimized = False

    def showNormal(self):
        self.show_normal_calls += 1
        self.maximized = False
        self.minimized = False

    def set_dropdown_popup_sizes(self, sizes):
        self.dropdown_sizes = dict(sizes)

    def windowState(self):
        state = QtCore.Qt.WindowState.WindowNoState
        if self.minimized:
            state |= QtCore.Qt.WindowState.WindowMinimized
        if self.maximized:
            state |= QtCore.Qt.WindowState.WindowMaximized
        return state

    def raise_(self):
        self.raise_calls += 1

    def activateWindow(self):
        self.activate_calls += 1


class WorkspaceStateCoordinatorDetachedWindowTests(unittest.TestCase):
    def _coordinator_for_window(self, window, *, is_maximized: bool):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._tracked_detached_windows = {
            WorkspaceStateCoordinator._DETACHED_ANNOTATION: window
        }
        coordinator._detached_restore_applied = {}
        coordinator._state = WorkspaceState()
        state = coordinator._state.detached_windows.annotation_view
        state.geometry_b64 = _encoded_geometry()
        state.is_maximized = is_maximized
        coordinator._state.takeoff_workspace.dropdown_popup_sizes = {
            "annotation_page": [320, 360]
        }
        return coordinator

    def test_saved_windowed_state_restores_geometry_without_maximizing(self):
        window = FakeDetachedWindow(visible=True, maximized=True)
        coordinator = self._coordinator_for_window(window, is_maximized=False)
        coordinator._apply_saved_detached_state(
            WorkspaceStateCoordinator._DETACHED_ANNOTATION,
            window,
        )
        self.assertEqual(window.restored_geometries, [b"geometry", b"geometry"])
        self.assertEqual(window.show_normal_calls, 1)
        self.assertEqual(window.show_maximized_calls, 0)
        self.assertEqual(window.dropdown_sizes, {"annotation_page": [320, 360]})

    def test_saved_maximized_state_restores_maximized_intentionally(self):
        window = FakeDetachedWindow(visible=True, maximized=False)
        coordinator = self._coordinator_for_window(window, is_maximized=True)
        coordinator._apply_saved_detached_state(
            WorkspaceStateCoordinator._DETACHED_ANNOTATION,
            window,
        )
        self.assertEqual(window.restored_geometries, [b"geometry"])
        self.assertEqual(window.show_maximized_calls, 1)
        self.assertEqual(window.show_normal_calls, 0)

    def test_hidden_window_receives_initial_state_before_show(self):
        window = FakeDetachedWindow(visible=False)
        coordinator = self._coordinator_for_window(window, is_maximized=False)
        coordinator._apply_saved_detached_state(
            WorkspaceStateCoordinator._DETACHED_ANNOTATION,
            window,
        )
        self.assertEqual(window.initial_states, [(b"geometry", False)])
        self.assertEqual(window.show_maximized_calls, 0)

    def test_public_tracking_methods_schedule_detached_page_windows(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        scheduled = []
        coordinator._schedule_track_detached_window = scheduled.append
        coordinator.track_annotation_window()
        coordinator.track_view_window()
        self.assertEqual(
            scheduled,
            [
                WorkspaceStateCoordinator._DETACHED_ANNOTATION,
                WorkspaceStateCoordinator._DETACHED_VIEW,
            ],
        )


class DetachedPageViewManagerBringToFrontTests(unittest.TestCase):
    def test_bring_to_front_does_not_maximize_windowed_minimized_window(self):
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = FakeDetachedWindow(minimized=True, maximized=False)
        manager.bring_to_front()
        self.assertEqual(manager._window.show_normal_calls, 1)
        self.assertEqual(manager._window.show_maximized_calls, 0)
        self.assertEqual(manager._window.raise_calls, 1)
        self.assertEqual(manager._window.activate_calls, 1)

    def test_bring_to_front_preserves_maximized_minimized_window(self):
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = FakeDetachedWindow(minimized=True, maximized=True)
        manager.bring_to_front()
        self.assertEqual(manager._window.show_maximized_calls, 1)
        self.assertEqual(manager._window.show_normal_calls, 0)


class OpenAnnotationViewUseCaseHotlinkTests(unittest.TestCase):
    def test_hotlink_open_targets_resolved_named_view_page(self):
        bid_ref = BidRef(file_path="job.ost", bid_uid="bid-1")
        named_view = BidAnnotation(
            uid="view-1",
            annotation_type="namedview",
            page_uid="page-2",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 5.0, 0.0, 5.0],
        )
        project_data = SimpleNamespace(
            get_current_bid_ref=lambda: bid_ref,
            get_all_annotations=lambda: [named_view],
        )
        calls = []
        view_manager = SimpleNamespace(
            is_view_open=lambda: False,
            open_view=lambda **kwargs: calls.append(kwargs) or "view-id",
        )
        use_case = OpenAnnotationViewUseCase(view_manager, project_data)
        result = use_case.execute_from_hotlink(
            AppEvents.HOTLINK_CLICKED(
                hotlink_uid="hotlink-1",
                bid_page_uid="page-1",
                target_view_uid="view-1",
                position_x=1.0,
                position_y=2.0,
            )
        )
        self.assertEqual(result, "view-id")
        self.assertEqual(calls[0]["bid_ref"], bid_ref)
        self.assertEqual(calls[0]["target_page_uid"], "page-2")
        self.assertEqual(calls[0]["target_named_view_uid"], "view-1")


if __name__ == "__main__":
    unittest.main()
