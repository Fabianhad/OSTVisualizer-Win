import unittest
from types import SimpleNamespace
from PySide6 import QtCore
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.use_cases.annotation_view.open_annotation_view_use_case import (
    OpenAnnotationViewUseCase,
)
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.workspace_state import WorkspaceState
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.coordinators.workspace_state_coordinator import (
    WorkspaceStateCoordinator,
)
from ost_visualizer.presentation.managers.detached_page_view_manager import (
    DetachedPageViewManager,
)


def _encoded_geometry(value: bytes = b"geometry") -> str:
    return bytes(QtCore.QByteArray(value).toBase64()).decode("ascii")


class WorkspaceStateDecodeTests(unittest.TestCase):
    def test_decode_byte_array_rejects_corrupted_non_string_state(self):
        decoded = WorkspaceStateCoordinator._decode_byte_array(123)
        self.assertTrue(decoded.isEmpty())


class FakeHotlinkPlanView:
    def __init__(self, *, visible: bool = True, stable: bool = True):
        self.current_page_uid = None
        self._visible = visible
        self._stable = stable
        self.deferred_states = []
        self.reveals = 0
        self.zoom_rects = []

    @property
    def is_view_state_stable(self):
        return self._stable

    def isVisible(self):
        return self._visible

    def set_page_visual_reveal_deferred(self, deferred):
        self.deferred_states.append(bool(deferred))

    def reveal_deferred_page_visual(self):
        self.reveals += 1

    def zoom_to_rect(self, min_x, min_y, max_x, max_y, margin):
        self.zoom_rects.append((min_x, min_y, max_x, max_y, margin))


class FakeHotlinkViewer:
    def __init__(self, plan_view):
        self.plan_view = plan_view
        self.updated_pages = []

    def update_plan_view(self, page_uid):
        self.updated_pages.append(page_uid)
        self.plan_view.current_page_uid = page_uid


class FakeHotlinkSidebar:
    def __init__(self):
        self.quantity_updates = 0

    def update_conditions_quantities(self):
        self.quantity_updates += 1


class FakeWorkspaceSaveTimer:
    def __init__(self, active=True):
        self._active = active
        self.stopped = False

    def isActive(self):
        return self._active

    def stop(self):
        self.stopped = True
        self._active = False


class FakeWorkspaceStateModel:
    def __init__(self):
        self.updated_states = []

    def update_state(self, state):
        self.updated_states.append(state)


class FakeHotlinkTabWidget:
    def currentIndex(self):
        return TAB_INDEX_TAKEOFF


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
        self.installed_filters = []
        self.dropdown_size_changed = SimpleNamespace(connect=lambda callback: None)
        self.destroyed = SimpleNamespace(connect=lambda callback: None)

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

    def installEventFilter(self, event_filter):
        self.installed_filters.append(event_filter)

    def removeEventFilter(self, event_filter):
        if event_filter in self.installed_filters:
            self.installed_filters.remove(event_filter)


class TrackableSignal:
    def __init__(self):
        self.connected = []
        self.disconnected = []

    def connect(self, callback):
        self.connected.append(callback)

    def disconnect(self, callback):
        self.disconnected.append(callback)


class TrackableDetachedWindow:
    def __init__(self):
        self.installed_filters = []
        self.dropdown_size_changed = TrackableSignal()
        self.destroyed = TrackableSignal()

    def installEventFilter(self, event_filter):
        self.installed_filters.append(event_filter)

    def removeEventFilter(self, event_filter):
        if event_filter in self.installed_filters:
            self.installed_filters.remove(event_filter)


class FakeSignal:
    def __init__(self, calls):
        self._calls = calls

    def connect(self, callback):
        self._calls.append("destroyed_connected")


class FakeConstructedWindow:
    def __init__(self, calls):
        self._calls = calls
        self.destroyed = FakeSignal(calls)

    def set_read_only(self, read_only):
        self._calls.append(("set_read_only", read_only))

    def show_when_page_ready(self):
        self._calls.append("show_when_page_ready")


class FakeCombo:
    def __init__(self):
        self.items = []
        self.blocked = False
        self.current_index = None

    def blockSignals(self, blocked):
        self.blocked = blocked

    def clear(self):
        self.items = []

    def addItem(self, text, userData=None):
        self.items.append((text, userData))

    def setCurrentIndex(self, index):
        self.current_index = index


class WorkspaceStateCoordinatorDetachedWindowTests(unittest.TestCase):
    def _coordinator_for_window(
        self,
        window,
        *,
        key=WorkspaceStateCoordinator._DETACHED_ANNOTATION,
        is_maximized: bool,
    ):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._tracked_detached_windows = {key: window}
        coordinator._detached_restore_applied = {}
        coordinator._state = WorkspaceState()
        state = coordinator._get_detached_window_state(key)
        state.geometry_b64 = _encoded_geometry()
        state.is_maximized = is_maximized
        coordinator._state.takeoff_workspace.dropdown_popup_sizes = {
            "annotation_page": [320, 360]
        }
        return coordinator

    def test_saved_mesh_windowed_state_restores_geometry_without_maximizing(self):
        window = FakeDetachedWindow(visible=True, maximized=True)
        coordinator = self._coordinator_for_window(
            window,
            key=WorkspaceStateCoordinator._DETACHED_MESH,
            is_maximized=False,
        )
        coordinator._apply_saved_mesh_window_state(window)
        self.assertEqual(window.restored_geometries, [b"geometry", b"geometry"])
        self.assertEqual(window.show_normal_calls, 1)
        self.assertEqual(window.show_maximized_calls, 0)

    def test_saved_mesh_maximized_state_restores_maximized_intentionally(self):
        window = FakeDetachedWindow(visible=True, maximized=False)
        coordinator = self._coordinator_for_window(
            window,
            key=WorkspaceStateCoordinator._DETACHED_MESH,
            is_maximized=True,
        )
        coordinator._apply_saved_mesh_window_state(window)
        self.assertEqual(window.restored_geometries, [b"geometry"])
        self.assertEqual(window.show_maximized_calls, 1)
        self.assertEqual(window.show_normal_calls, 0)

    def test_hidden_mesh_window_receives_initial_state_before_show(self):
        window = FakeDetachedWindow(visible=False)
        coordinator = self._coordinator_for_window(
            window,
            key=WorkspaceStateCoordinator._DETACHED_MESH,
            is_maximized=False,
        )
        coordinator._apply_saved_mesh_window_state(window)
        self.assertEqual(window.initial_states, [(b"geometry", False)])
        self.assertEqual(window.show_maximized_calls, 0)

    def test_tracked_page_window_keeps_pre_show_geometry(self):
        window = FakeDetachedWindow(visible=True, maximized=True)
        coordinator = self._coordinator_for_window(window, is_maximized=False)
        coordinator._complete_detached_window_tracking(
            WorkspaceStateCoordinator._DETACHED_ANNOTATION,
            window,
        )
        self.assertEqual(window.initial_states, [])
        self.assertEqual(window.restored_geometries, [])
        self.assertEqual(window.show_normal_calls, 0)
        self.assertEqual(window.show_maximized_calls, 0)
        self.assertEqual(window.dropdown_sizes, {"annotation_page": [320, 360]})

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

    def test_reset_to_defaults_persists_default_workspace_and_reapplies_state(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        timer = FakeWorkspaceSaveTimer(active=True)
        model = FakeWorkspaceStateModel()
        restored = []
        coordinator._save_timer = timer
        coordinator.workspace_state_model = model
        coordinator._state = WorkspaceState()
        coordinator._state.takeoff_workspace.active_view = "2d"
        coordinator._pending_takeoff_splitter_sizes = [100, 200]
        coordinator._pending_splitter_sizes = [30, 70]
        coordinator._pending_mesh_restore = True
        coordinator._pending_annotation_restore = True
        coordinator._pending_view_restore = True
        coordinator.restore_initial_state = lambda: restored.append("restore")
        coordinator.reset_to_defaults()
        self.assertTrue(timer.stopped)
        self.assertEqual(model.updated_states, [WorkspaceState()])
        self.assertEqual(coordinator._state, WorkspaceState())
        self.assertEqual(coordinator._pending_takeoff_splitter_sizes, [])
        self.assertEqual(coordinator._pending_splitter_sizes, [])
        self.assertFalse(coordinator._pending_mesh_restore)
        self.assertFalse(coordinator._pending_annotation_restore)
        self.assertFalse(coordinator._pending_view_restore)
        self.assertEqual(restored, ["restore"])

    def test_untracking_detached_window_releases_filters_and_callbacks(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        window = TrackableDetachedWindow()
        callback = lambda *_args: None
        key = WorkspaceStateCoordinator._DETACHED_ANNOTATION
        coordinator._tracked_detached_destroy_callbacks = {key: callback}
        window.installEventFilter(coordinator)
        window.dropdown_size_changed.connect(coordinator.request_save)
        window.destroyed.connect(callback)
        coordinator._untrack_detached_window(key, window)
        self.assertEqual(window.installed_filters, [])
        self.assertEqual(
            window.dropdown_size_changed.disconnected,
            [coordinator.request_save],
        )
        self.assertEqual(window.destroyed.disconnected, [callback])
        self.assertEqual(coordinator._tracked_detached_destroy_callbacks, {})

    def test_tracked_window_destroy_drops_reference_after_cleanup(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        key = WorkspaceStateCoordinator._DETACHED_VIEW
        window = TrackableDetachedWindow()
        coordinator._tracked_detached_windows = {key: window}
        coordinator._tracked_detached_destroy_callbacks = {key: lambda *_args: None}
        coordinator._detached_restore_applied = {key: True}
        coordinator._save_timer = None
        coordinator._on_tracked_window_destroyed(key)
        self.assertEqual(coordinator._tracked_detached_windows, {})
        self.assertEqual(coordinator._tracked_detached_destroy_callbacks, {})
        self.assertEqual(coordinator._detached_restore_applied, {})


class DetachedPageViewManagerLifecycleTests(unittest.TestCase):
    def test_create_window_defers_first_show_until_after_manager_setup(self):
        calls = []
        factory_kwargs = []
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.icon_provider = object()
        manager.event_bus = object()
        manager.project_data = SimpleNamespace(
            get_bid=lambda bid_ref: None,
            get_current_bid_file_path=lambda: None,
            get_all_takeoffs=lambda: [],
        )
        manager.config_model = Config()
        manager._coord_factory = SimpleNamespace(create=lambda: object())
        manager._color_service = object()
        manager._infrastructure_provider = SimpleNamespace(
            create_plan_view_renderers=lambda _coord_system, _color_service: object()
        )
        manager._window_factory = lambda **kwargs: factory_kwargs.append(
            kwargs
        ) or FakeConstructedWindow(calls)
        manager._annotation_write_service = None
        manager._write_service = None
        manager.parent_window = None
        manager._on_window_destroyed = lambda *args: None
        manager._on_window_page_selected = lambda page_uid: None
        manager._on_window_named_view_selected = lambda page_uid, _named_view_uid: None
        manager._on_window_scale_changed = lambda page_uid, _sf1, _sf2: None
        manager._collect_pages_with_takeoffs = lambda bid_ref: set()
        manager._is_read_only = lambda: False
        manager._get_page_data = lambda view: SimpleNamespace(page=object())
        view = SimpleNamespace(uid="view-1", bid_ref=None)
        geometry = QtCore.QByteArray(b"geometry")
        manager._create_window(view, geometry, False)
        self.assertEqual(factory_kwargs[0]["initial_geometry"], geometry)
        self.assertFalse(factory_kwargs[0]["initial_is_maximized"])
        self.assertEqual(
            calls,
            [
                ("set_read_only", False),
                "destroyed_connected",
                "show_when_page_ready",
            ],
        )

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

    def test_named_view_rename_event_updates_open_window_combo(self):
        calls = []
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.project_data = SimpleNamespace(
            update_named_view_names=lambda updates: calls.append(tuple(updates))
        )
        manager._window = SimpleNamespace(
            update_named_view_name=lambda uid, name: calls.append((uid, name))
        )
        manager._on_named_view_renamed("nv1", "Updated View")
        self.assertEqual(calls[0], (("nv1", "Updated View"),))
        self.assertEqual(calls[1], ("nv1", "Updated View"))

    def test_named_view_rename_event_does_not_touch_closed_window(self):
        calls = []
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.project_data = SimpleNamespace(
            update_named_view_names=lambda updates: calls.append(tuple(updates))
        )
        manager._window = None
        manager._on_named_view_renamed("nv1", "Updated View")
        self.assertEqual(calls, [(("nv1", "Updated View"),)])

    def test_detached_window_named_view_combo_uses_renamed_text(self):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        plan_view_calls = []
        annotation = BidAnnotation(
            uid="nv1",
            annotation_type="namedview",
            page_uid="p1",
            properties={"Text": "Old View"},
        )
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._is_closing = False
        window._named_views = [("nv1", "p1", "Page 1", "Old View")]
        window._named_view_combo = FakeCombo()
        window._page_combo = SimpleNamespace(get_page_order=lambda: ["p1"])
        window.page_data = SimpleNamespace(annotations=[annotation])
        window.plan_view = SimpleNamespace(
            update_named_view_label_text=lambda uid, name: plan_view_calls.append(
                (uid, name)
            )
        )
        window.update_named_view_name("nv1", "Updated View")
        self.assertEqual(
            window._named_view_combo.items,
            [("Updated View", ("p1", "nv1"))],
        )
        self.assertEqual(annotation.properties["Text"], "Updated View")
        self.assertEqual(plan_view_calls, [("nv1", "Updated View")])


class OpenAnnotationViewUseCaseHotlinkTests(unittest.TestCase):
    def _make_main_hotlink_coordinator(self, plan_view):
        page = Page(uid="page-2", name="Page 2")
        named_view = BidAnnotation(
            uid="view-1",
            annotation_type="namedview",
            page_uid="page-2",
            position=[1.0, 2.0, 11.0, 2.0, 11.0, 12.0, 1.0, 12.0],
        )
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.project_data = SimpleNamespace(
            get_page=lambda uid: page if uid == "page-2" else None,
            get_page_annotations=lambda uid: [named_view] if uid == "page-2" else [],
        )
        coordinator.plan_view = plan_view
        coordinator._viewer = FakeHotlinkViewer(plan_view)
        coordinator._sidebar = FakeHotlinkSidebar()
        coordinator._tab_widget = FakeHotlinkTabWidget()
        coordinator._set_takeoff_tab_visible = lambda visible: None
        coordinator._activate_takeoff_workspace = lambda: coordinator._update_plan_view(
            "page-2"
        )
        coordinator._pending_takeoff_page_uids = None
        coordinator._pending_takeoff_active_page_uid = None
        coordinator._pending_takeoff_selected_area_uid = ""
        coordinator._pending_takeoff_place_condition_uid = None
        coordinator._pending_takeoff_place_condition_uids = []
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        return coordinator

    def test_main_hotlink_focus_uses_named_view_rectangle_after_page_update(self):
        plan_view = FakeHotlinkPlanView()
        coordinator = self._make_main_hotlink_coordinator(plan_view)
        coordinator.navigate_to_takeoff_page("page-2", "view-1")
        self.assertEqual(coordinator._viewer.updated_pages, ["page-2"])
        self.assertEqual(plan_view.deferred_states, [True])
        self.assertEqual(plan_view.zoom_rects, [(1.0, 2.0, 11.0, 12.0, 0.1)])
        self.assertEqual(plan_view.reveals, 1)

    def test_main_hotlink_focus_on_loaded_page_does_not_defer_visuals(self):
        plan_view = FakeHotlinkPlanView()
        plan_view.current_page_uid = "page-2"
        coordinator = self._make_main_hotlink_coordinator(plan_view)
        coordinator.navigate_to_takeoff_page("page-2", "view-1")
        self.assertEqual(plan_view.deferred_states, [])
        self.assertEqual(plan_view.zoom_rects, [(1.0, 2.0, 11.0, 12.0, 0.1)])

    def test_main_hotlink_focus_waits_until_plan_view_is_visible(self):
        plan_view = FakeHotlinkPlanView(visible=False)
        coordinator = self._make_main_hotlink_coordinator(plan_view)
        coordinator.navigate_to_takeoff_page("page-2", "view-1")
        self.assertEqual(plan_view.zoom_rects, [])
        self.assertEqual(plan_view.reveals, 0)
        plan_view._visible = True
        coordinator._on_plan_view_page_fully_loaded()
        self.assertEqual(plan_view.zoom_rects, [(1.0, 2.0, 11.0, 12.0, 0.1)])
        self.assertEqual(plan_view.reveals, 1)

    def test_main_hotlink_pending_focus_clears_when_another_page_loads(self):
        plan_view = FakeHotlinkPlanView(visible=False)
        coordinator = self._make_main_hotlink_coordinator(plan_view)
        coordinator.navigate_to_takeoff_page("page-2", "view-1")
        plan_view._visible = True
        plan_view.current_page_uid = "page-3"
        coordinator._on_plan_view_page_fully_loaded()
        plan_view.current_page_uid = "page-2"
        coordinator._on_plan_view_page_fully_loaded()
        self.assertEqual(plan_view.zoom_rects, [])
        self.assertEqual(plan_view.reveals, 1)

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

    def test_hotlink_preference_can_route_to_view_window_manager(self):
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
        annotation_calls = []
        view_calls = []
        annotation_manager = SimpleNamespace(
            is_view_open=lambda: False,
            open_view=lambda **kwargs: annotation_calls.append(kwargs) or "annotation",
        )
        view_manager = SimpleNamespace(
            is_view_open=lambda: False,
            open_view=lambda **kwargs: view_calls.append(kwargs) or "view",
        )
        use_case = OpenAnnotationViewUseCase(
            annotation_manager,
            project_data,
            config_model=Config(hotlink_target="view"),
            view_window_manager=view_manager,
        )
        result = use_case.execute_from_hotlink(
            AppEvents.HOTLINK_CLICKED(
                hotlink_uid="hotlink-1",
                bid_page_uid="page-1",
                target_view_uid="view-1",
            )
        )
        self.assertEqual(result, "view")
        self.assertEqual(annotation_calls, [])
        self.assertEqual(view_calls[0]["target_page_uid"], "page-2")

    def test_hotlink_preference_can_route_to_main_window_manager(self):
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
        annotation_calls = []
        view_calls = []
        main_calls = []
        annotation_manager = SimpleNamespace(
            is_view_open=lambda: False,
            open_view=lambda **kwargs: annotation_calls.append(kwargs) or "annotation",
        )
        view_manager = SimpleNamespace(
            is_view_open=lambda: False,
            open_view=lambda **kwargs: view_calls.append(kwargs) or "view",
        )
        main_manager = SimpleNamespace(
            is_view_open=lambda: True,
            bring_to_front=lambda: main_calls.append(("front",)),
            navigate_to_view=lambda page_uid, named_view_uid: main_calls.append(
                (page_uid, named_view_uid)
            ),
        )
        use_case = OpenAnnotationViewUseCase(
            annotation_manager,
            project_data,
            config_model=Config(hotlink_target="main"),
            view_window_manager=view_manager,
            main_view_manager=main_manager,
        )
        result = use_case.execute_from_hotlink(
            AppEvents.HOTLINK_CLICKED(
                hotlink_uid="hotlink-1",
                bid_page_uid="page-1",
                target_view_uid="view-1",
            )
        )
        self.assertEqual(result, "__current__")
        self.assertEqual(annotation_calls, [])
        self.assertEqual(view_calls, [])
        self.assertEqual(main_calls, [("front",), ("page-2", "view-1")])


if __name__ == "__main__":
    unittest.main()
