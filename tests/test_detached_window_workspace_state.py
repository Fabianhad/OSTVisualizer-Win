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
from ost_visualizer.presentation.windows.components.window import DetachedPageViewWindow
from ost_visualizer.presentation.managers.detached_page_view_manager import (
    DetachedPageViewManager,
)
from ost_visualizer.presentation.utils.plan_tool_registry import (
    PLAN_ANNOTATION_TOOL_SPECS,
)
from ost_visualizer.presentation.windows.annotation_view_window import (
    _ANNOTATION_WINDOW_CONFIG,
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
        self.started = False

    def isActive(self):
        return self._active

    def stop(self):
        self.stopped = True
        self._active = False

    def start(self):
        self.started = True
        self._active = True


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


class FakeDetachedPlanView:
    def __init__(self, annotations=None):
        self.annotations = {ann.uid: ann for ann in annotations or []}
        self.restored_positions = []
        self.restored_text_properties = []
        self.restored_text_and_positions = []
        self.selected_uids = set()
        self.annotation_key_map = {}
        self.cleared = False

    def restore_flushed_positions(self, takeoff_changes, ann_changes):
        self.restored_positions.append((list(takeoff_changes), list(ann_changes)))

    def restore_annotation_text_properties(self, changes):
        self.restored_text_properties.append(list(changes))

    def restore_annotation_text_and_positions(self, text_changes, ann_position_changes):
        self.restored_text_and_positions.append(
            (list(text_changes), list(ann_position_changes))
        )

    def restore_annotation_styles(self, changes):
        self.restored_annotation_styles = list(changes)

    def get_annotation(self, uid):
        return self.annotations.get(uid)

    def set_selected_uids(self, uids):
        self.selected_uids = set(uids)

    def clear_selection(self):
        self.cleared = True
        self.selected_uids = set()

    def find_annotation_keys_by_uid_type(self, uid_type_set):
        return {
            self.annotation_key_map[(uid, ann_type)]
            for uid, ann_type in uid_type_set
            if (uid, ann_type) in self.annotation_key_map
        }


class FakeAnnotationWriteService:
    def __init__(self):
        self.insert_calls = []
        self.style_calls = []
        self.next_uids = ["ann-1"]

    def insert_annotations(self, db_path, bid_uid, specs, ref_remap=None):
        self.insert_calls.append((db_path, bid_uid, specs, ref_remap))
        return list(self.next_uids[: len(specs)])

    def save_annotation_styles(self, db_path, updates):
        self.style_calls.append((db_path, updates))
        return True


class FakeUndoService:
    def __init__(self):
        self.pushes = []

    def push(self, undo, redo):
        self.pushes.append((undo, redo))


class TrackableSignal:
    def __init__(self):
        self.connected = []
        self.disconnected = []

    def connect(self, callback):
        self.connected.append(callback)

    def disconnect(self, callback):
        self.disconnected.append(callback)


class CleanupSignal:
    def __init__(self):
        self.disconnected = []

    def disconnect(self, callback):
        self.disconnected.append(callback)


class CleanupPlanView:
    def __init__(self):
        self.page_geometry_ready = CleanupSignal()
        self.page_fully_loaded = CleanupSignal()
        self.positions_flushed = CleanupSignal()
        self.annotation_text_properties_flushed = CleanupSignal()
        self.annotation_text_and_positions_flushed = CleanupSignal()
        self.annotation_styles_flushed = CleanupSignal()
        self.elements_deleted = CleanupSignal()
        self.annotation_created = CleanupSignal()
        self.text_annotation_created = CleanupSignal()
        self.cursor_mode_change_requested = CleanupSignal()
        self.undo_requested = CleanupSignal()
        self.redo_requested = CleanupSignal()
        self.blocked = None
        self.cleaned = False

    def blockSignals(self, blocked):
        self.blocked = bool(blocked)

    def cleanup(self):
        self.cleaned = True


class CleanupCombo:
    def __init__(self):
        self.page_activated = CleanupSignal()
        self.currentIndexChanged = CleanupSignal()
        self.cleaned = False

    def cleanup(self):
        self.cleaned = True

    def cleanup_popup(self):
        self.cleaned = True


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


class FakeButton:
    def __init__(self):
        self.enabled = None

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)


class FakePageCombo:
    def __init__(self):
        self.loaded_bid = None
        self.cleared = False
        self.selected_uid = None
        self.pages_with_takeoffs = None
        self.label_options = None
        self.order = []

    def set_label_options(self, show_page_index, show_sheet_number):
        self.label_options = (bool(show_page_index), bool(show_sheet_number))

    def load_bid(self, bid, pages_with_takeoffs=None):
        self.loaded_bid = bid
        self.cleared = False
        self.pages_with_takeoffs = set(pages_with_takeoffs or ())
        self.order = [page.uid for page in bid.pages_without_folder]

    def clear(self):
        self.cleared = True
        self.loaded_bid = None
        self.order = []

    def get_page_order(self):
        return list(self.order)

    def set_current_page_uid(self, uid):
        self.selected_uid = uid

    def set_pages_with_takeoffs(self, page_uids):
        self.pages_with_takeoffs = set(page_uids or ())


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

    def test_late_request_save_after_cleanup_is_ignored(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        timer = FakeWorkspaceSaveTimer(active=False)
        coordinator._cleaned_up = True
        coordinator._save_timer = timer
        coordinator.request_save()
        self.assertFalse(timer.started)

    def test_late_detached_restore_after_cleanup_is_ignored(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._cleaned_up = True
        coordinator._takeoff_workspace_ready_restore_scheduled = True
        coordinator._restore_detached_page_windows_when_ready()
        self.assertTrue(coordinator._takeoff_workspace_ready_restore_scheduled)

    def test_late_detached_tracking_after_cleanup_is_ignored(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._cleaned_up = True
        coordinator._track_detached_window(WorkspaceStateCoordinator._DETACHED_VIEW)

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
        coordinator._cleaned_up = False
        coordinator._on_tracked_window_destroyed(key)
        self.assertEqual(coordinator._tracked_detached_windows, {})
        self.assertEqual(coordinator._tracked_detached_destroy_callbacks, {})
        self.assertEqual(coordinator._detached_restore_applied, {})

    def test_detached_page_window_cleanup_releases_renderer_references(self):
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        retained = object()
        plan_view = CleanupPlanView()
        window._is_closing = False
        window._show_timer = None
        window._named_view_resize_focus_timer = None
        window._pending_named_view_resize_focus = False
        window._reveal_named_view_blank_canvas = lambda: None
        window._hotlink_adapter = None
        window.plan_view = plan_view
        window._undo_svc = None
        window._ann_write_svc = retained
        window._file_path = "file.mdb"
        window._renderers = retained
        window._color_service = retained
        window._config = retained
        window._pages_with_takeoffs = {"page-1"}
        window._on_page_selected = lambda _uid: None
        window._on_named_view_selected = lambda _page, _view: None
        window._on_scale_changed = lambda _page, _sf1, _sf2: None
        window._page_combo = CleanupCombo()
        window._named_view_combo = CleanupCombo()
        window._scale_combo = retained
        window._btn_select = retained
        window._named_views = [retained]
        window.event_bus = retained
        window.view = retained
        window.page_data = retained
        window.icon_provider = retained
        DetachedPageViewWindow.cleanup(window)
        self.assertTrue(plan_view.cleaned)
        self.assertIsNone(window.plan_view)
        self.assertIsNone(window._renderers)
        self.assertIsNone(window._color_service)
        self.assertIsNone(window._config)
        self.assertEqual(window._pages_with_takeoffs, set())
        self.assertIsNone(window._page_combo)
        self.assertIsNone(window._named_view_combo)
        self.assertIsNone(window._scale_combo)
        self.assertIsNone(window._btn_select)


class DetachedPageViewManagerLifecycleTests(unittest.TestCase):
    def test_annotation_window_uses_shared_annotation_tool_specs_only(self):
        self.assertEqual(
            _ANNOTATION_WINDOW_CONFIG.annotation_tool_specs,
            PLAN_ANNOTATION_TOOL_SPECS,
        )
        self.assertEqual(
            [
                spec.action_key
                for spec in _ANNOTATION_WINDOW_CONFIG.annotation_tool_specs
            ],
            [
                "dimension_tool",
                "text_annotation_tool",
                "highlight_annotation_tool",
                "arrow_annotation_tool",
                "line_annotation_tool",
                "rectangle_annotation_tool",
                "oval_annotation_tool",
                "polygon_annotation_tool",
                "cloud_annotation_tool",
                "ink_annotation_tool",
            ],
        )
        self.assertEqual(
            [
                spec.annotation_type
                for spec in _ANNOTATION_WINDOW_CONFIG.annotation_tool_specs
            ],
            [
                "dimension",
                "text",
                "highlight",
                "arrow",
                "line",
                "rect",
                "oval",
                "polygon",
                "cloud",
                "ink",
            ],
        )
        self.assertNotIn(
            "place_tool",
            [
                spec.action_key
                for spec in _ANNOTATION_WINDOW_CONFIG.annotation_tool_specs
            ],
        )

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

    def test_refresh_window_updates_navigation_before_page_content(self):
        calls = []
        view = SimpleNamespace(uid="view-1", bid_ref=BidRef("file.mdb", "bid-1"))
        page_data = SimpleNamespace(page=Page(uid="p1", name="Page 1"))
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = SimpleNamespace(
            set_read_only=lambda read_only: calls.append(("read_only", read_only)),
            update_page=lambda data: calls.append(("page", data.page.uid)),
        )
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager._get_page_data = lambda active_view: page_data
        manager._update_window_navigation = lambda active_view: calls.append(
            ("navigation", active_view.uid)
        )
        manager._is_read_only = lambda: False
        manager._refresh_window()
        self.assertEqual(
            calls,
            [("navigation", "view-1"), ("read_only", False), ("page", "p1")],
        )

    def test_failed_detached_scale_save_refreshes_window_state(self):
        calls = []
        view = SimpleNamespace(file_path="file.mdb")
        write_service = SimpleNamespace(
            save_page_scale=lambda db_path, page_uid, sf1, sf2: calls.append(
                ("save", db_path, page_uid, sf1, sf2)
            )
            or False
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._write_service = write_service
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.project_data = SimpleNamespace(get_current_bid_file_path=lambda: None)
        manager._refresh_window = lambda: calls.append("refresh")
        manager.logger = SimpleNamespace(exception=lambda *args, **kwargs: None)
        manager._on_window_scale_changed("page-1", 0.25, 12.0)
        self.assertEqual(calls, [("save", "file.mdb", "page-1", 0.25, 12.0), "refresh"])

    def test_open_existing_detached_view_rebuilds_navigation_before_load(self):
        calls = []
        existing_view = SimpleNamespace(
            uid="view-1",
            bid_uid="old-bid",
            file_path="old.mdb",
            bid_ref=BidRef("old.mdb", "old-bid"),
            target_page_uid="old-page",
            update_view_target=lambda page_uid, named_view_uid=None: calls.append(
                ("target", page_uid, named_view_uid)
            ),
        )
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = SimpleNamespace(
            load_view=lambda view, data, navigation_source="unknown": calls.append(
                ("load", view.bid_uid, view.file_path, data, navigation_source)
            )
        )
        manager.repository = SimpleNamespace(
            get_active_view=lambda: existing_view,
            update_view=lambda view: calls.append(
                ("repo", view.bid_uid, view.file_path)
            ),
        )
        manager._update_window_navigation = lambda view: calls.append(
            ("navigation", view.bid_uid, view.file_path)
        )
        manager._get_page_data = lambda view: "page-data"
        manager.bring_to_front = lambda: calls.append("front")
        manager._notify_visibility_changed = lambda: calls.append("notify")
        result = manager.open_view(
            BidRef("new.mdb", "new-bid"), "new-page", "named-view"
        )
        self.assertEqual(result, "view-1")
        self.assertEqual(
            calls,
            [
                ("target", "new-page", "named-view"),
                ("repo", "new-bid", "new.mdb"),
                ("navigation", "new-bid", "new.mdb"),
                ("load", "new-bid", "new.mdb", "page-data", "hotlink"),
                "front",
                "notify",
            ],
        )

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

    def test_detached_annotation_position_save_failure_restores_plan_view(self):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        plan_view = FakeDetachedPlanView()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = False
        window._is_closing = False
        window._ann_write_svc = SimpleNamespace(
            save_annotation_positions=lambda *_args: False
        )
        window._file_path = "bid.mdb"
        window.plan_view = plan_view
        changes = [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
        window._on_positions_flushed([], changes)
        self.assertEqual(plan_view.restored_positions, [([], changes)])

    def test_detached_annotation_text_save_failure_restores_plan_view(self):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        plan_view = FakeDetachedPlanView()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = False
        window._is_closing = False
        window._ann_write_svc = SimpleNamespace(
            save_annotation_text_properties=lambda *_args: False
        )
        window._file_path = "bid.mdb"
        window.plan_view = plan_view
        changes = [("a1", "text", {"Text": "Old"}, {"Text": "New"})]
        window._on_annotation_text_properties_flushed(changes)
        self.assertEqual(plan_view.restored_text_properties, [changes])

    def test_detached_annotation_text_and_position_save_failure_restores_plan_view(
        self,
    ):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        plan_view = FakeDetachedPlanView()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = False
        window._is_closing = False
        window._ann_write_svc = SimpleNamespace(
            save_annotation_text_properties_and_positions=lambda *_args: False
        )
        window._file_path = "bid.mdb"
        window.plan_view = plan_view
        text_changes = [("a1", "text", {"Text": "Old"}, {"Text": "New"})]
        position_changes = [("a1", "text", [1.0, 1.0], [2.0, 2.0])]
        window._on_annotation_text_and_positions_flushed(text_changes, position_changes)
        self.assertEqual(
            plan_view.restored_text_and_positions,
            [(text_changes, position_changes)],
        )

    def test_detached_annotation_delete_failure_restores_selection(self):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        annotation = BidAnnotation(uid="a1", annotation_type="text", page_uid="p1")
        plan_view = FakeDetachedPlanView([annotation])
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = False
        window._is_closing = False
        window._ann_write_svc = SimpleNamespace(delete_annotations=lambda *_args: False)
        window._file_path = "bid.mdb"
        window.plan_view = plan_view
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._on_elements_deleted(["a1"])
        self.assertEqual(plan_view.selected_uids, {"a1"})

    def test_detached_annotation_creation_inserts_and_selects_annotation(
        self,
    ):
        for annotation_type in (
            "dimension",
            "highlight",
            "arrow",
            "line",
            "rect",
            "oval",
            "polygon",
            "cloud",
            "ink",
        ):
            with self.subTest(annotation_type=annotation_type):
                write_service = FakeAnnotationWriteService()
                undo_service = FakeUndoService()
                plan_view = FakeDetachedPlanView()
                plan_view.annotation_key_map[("ann-1", annotation_type)] = (
                    f"ann-1_{annotation_type}"
                )
                window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
                window._config = SimpleNamespace(allow_annotation_editing=True)
                window._read_only = False
                window._is_closing = False
                window._ann_write_svc = write_service
                window._undo_svc = undo_service
                window.plan_view = plan_view
                window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
                position = (
                    [1.0, 2.0, 3.0, 4.0, 5.0, 2.0]
                    if annotation_type in ("polygon", "cloud")
                    else [1.0, 2.0, 3.0, 4.0]
                )
                window._on_annotation_created(annotation_type, position, "p1")
                self.assertEqual(len(write_service.insert_calls), 1)
                db_path, bid_uid, specs, ref_remap = write_service.insert_calls[0]
                self.assertEqual((db_path, bid_uid, ref_remap), ("bid.mdb", "7", None))
                self.assertEqual(specs[0].annotation_type, annotation_type)
                self.assertEqual(specs[0].position, position)
                self.assertEqual(plan_view.selected_uids, {f"ann-1_{annotation_type}"})
                self.assertEqual(len(undo_service.pushes), 1)

    def test_detached_text_annotation_commit_uses_annotation_write_path(self):
        write_service = FakeAnnotationWriteService()
        undo_service = FakeUndoService()
        plan_view = FakeDetachedPlanView()
        plan_view.annotation_key_map[("ann-1", "text")] = "ann-1_text"
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = False
        window._is_closing = False
        window._ann_write_svc = write_service
        window._undo_svc = undo_service
        window.plan_view = plan_view
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        properties = {
            "Text": "Hello",
            "FontName": "Arial",
            "FontColor": 0x336699,
            "FontSize": 12,
            "FontBold": False,
            "FontItalic": False,
            "FontUnderline": False,
            "TextAlign": 0,
        }
        window._on_text_annotation_created(
            [7.0, 8.0, 12.0, 12.0],
            "p1",
            properties,
        )
        self.assertEqual(len(write_service.insert_calls), 1)
        db_path, bid_uid, specs, ref_remap = write_service.insert_calls[0]
        self.assertEqual((db_path, bid_uid, ref_remap), ("bid.mdb", "7", None))
        self.assertEqual(specs[0].annotation_type, "text")
        self.assertEqual(specs[0].position, [7.0, 8.0, 12.0, 12.0])
        self.assertEqual(specs[0].properties, properties)
        self.assertEqual(specs[0].color, "#996633")
        self.assertEqual(plan_view.selected_uids, {"ann-1_text"})
        self.assertEqual(len(undo_service.pushes), 1)

    def test_detached_empty_text_annotation_commit_is_not_written(self):
        write_service = FakeAnnotationWriteService()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = False
        window._is_closing = False
        window._ann_write_svc = write_service
        window._undo_svc = None
        window.plan_view = FakeDetachedPlanView()
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._on_text_annotation_created(
            [7.0, 8.0, 12.0, 12.0],
            "p1",
            {"Text": "   ", "FontColor": 0x336699},
        )
        self.assertEqual(write_service.insert_calls, [])

    def test_detached_annotation_style_change_uses_style_write_path(self):
        write_service = FakeAnnotationWriteService()
        undo_service = FakeUndoService()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = False
        window._is_closing = False
        window._ann_write_svc = write_service
        window._undo_svc = undo_service
        window.plan_view = FakeDetachedPlanView()
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._file_path = "bid.mdb"
        changes = [
            (
                "a1",
                "cloud",
                {"Color": "#ff0000", "Width": 4.0},
                {"Color": "#336699", "Width": 8.0},
            )
        ]
        window._on_annotation_styles_flushed(changes)
        self.assertEqual(
            write_service.style_calls,
            [("bid.mdb", [("a1", "cloud", {"Color": "#336699", "Width": 8.0})])],
        )
        self.assertEqual(len(undo_service.pushes), 1)

    def test_detached_dimension_annotation_creation_obeys_annotation_edit_gate(self):
        write_service = FakeAnnotationWriteService()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = True
        window._is_closing = False
        window._ann_write_svc = write_service
        window._undo_svc = None
        window.plan_view = FakeDetachedPlanView()
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._on_annotation_created("dimension", [1.0, 2.0, 3.0, 4.0], "p1")
        self.assertEqual(write_service.insert_calls, [])

    def test_detached_annotation_tool_activation_enters_annotation_placement(self):
        calls = []
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._read_only = False
        window.plan_view = SimpleNamespace(
            activate_annotation_placement=lambda annotation_type: calls.append(
                annotation_type
            )
            or True
        )
        for annotation_type in (
            "dimension",
            "text",
            "highlight",
            "arrow",
            "line",
            "rect",
            "oval",
            "polygon",
            "cloud",
            "ink",
        ):
            with self.subTest(annotation_type=annotation_type):
                self.assertTrue(window._activate_annotation_tool(annotation_type))
        self.assertEqual(
            calls,
            [
                "dimension",
                "text",
                "highlight",
                "arrow",
                "line",
                "rect",
                "oval",
                "polygon",
                "cloud",
                "ink",
            ],
        )

    def test_detached_window_navigation_refresh_rebuilds_page_and_view_models(self):
        from ost_visualizer.presentation.windows.components.window import (
            DetachedPageViewWindow,
        )

        bid = SimpleNamespace(
            pages_without_folder=[
                Page(uid="p1", name="Page 1"),
                Page(uid="p2", name="Page 2"),
            ]
        )
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._is_closing = False
        window._pages_with_takeoffs = set()
        window._named_views = [("stale", "old", "Old Page", "Old View")]
        window._show_page_index = True
        window._show_sheet_number = False
        window._page_combo = FakePageCombo()
        window._named_view_combo = FakeCombo()
        window._btn_prev = FakeButton()
        window._btn_next = FakeButton()
        window.view = SimpleNamespace(target_page_uid="p2")
        window.update_navigation(
            bid,
            named_views=[
                ("nv1", "p1", "Page 1", "View 1"),
                ("nv2", "p2", "Page 2", "View 2"),
                ("orphan", "missing", "Missing", "Missing View"),
            ],
            pages_with_takeoffs={"p1"},
        )
        self.assertIs(window._page_combo.loaded_bid, bid)
        self.assertEqual(window._page_combo.selected_uid, "p2")
        self.assertEqual(window._page_combo.pages_with_takeoffs, {"p1"})
        self.assertEqual(
            window._named_view_combo.items,
            [("View 1", ("p1", "nv1")), ("View 2", ("p2", "nv2"))],
        )
        self.assertTrue(window._btn_prev.enabled)
        self.assertFalse(window._btn_next.enabled)


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
