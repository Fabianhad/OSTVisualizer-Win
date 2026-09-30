import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.coordinators.workspace_state_coordinator import (
    WorkspaceStateCoordinator,
)
from types import SimpleNamespace
from ost_visualizer.application.dtos.condition_summary_dtos import (
    ConditionSummaryGrouping,
)
from ost_visualizer.domain.aggregates.workspace_state_aggregate import (
    WorkspaceStateAggregate,
)
from ost_visualizer.domain.entities.workspace_state import (
    HeaderLayoutState,
    WorkspaceState,
)
from PySide6 import QtCore, QtWidgets
from tests.helpers.workspace_state import InMemoryWorkspaceStateRepository
from tests.presentation.coordinators.workspace_restore_support import (
    FakeDetachedWindow as _detached_support_FakeDetachedWindow,
    FakeSplitterForSidebarSizes as _detached_support_FakeSplitterForSidebarSizes,
    FakeWorkspaceSaveTimer as _detached_support_FakeWorkspaceSaveTimer,
    RecordingWorkspaceStateRepository as _detached_support_RecordingWorkspaceStateRepository,
    _encoded_geometry as _detached_support__encoded_geometry,
    _workspace_state_model as _detached_support__workspace_state_model,
)
from tests.presentation.windows.detached_lifecycle_support import (
    TrackableDetachedWindow as _detached_support_TrackableDetachedWindow,
    TrackableSignal as _detached_support_TrackableSignal,
)


class WorkspaceStateDecodeTests(unittest.TestCase):
    def test_decode_byte_array_rejects_corrupted_non_string_state(self):
        decoded = WorkspaceStateCoordinator._decode_byte_array(123)
        self.assertTrue(decoded.isEmpty())


class WorkspaceStateCoordinatorDetachedWindowTests(unittest.TestCase):
    def test_workspace_cleanup_attempts_all_stages_and_retries_failures(self):
        disconnected = []

        class Signal:
            def __init__(self, name):
                self.name = name

            def disconnect(self, _callback):
                disconnected.append(self.name)

        class FilterOwner:
            def __init__(self, name):
                self.name = name
                self.attempts = 0

            def removeEventFilter(self, _filter):
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError(f"{self.name} failed")

        conditions = SimpleNamespace(group_by_type_changed=Signal("conditions"))
        summary = SimpleNamespace(summary_ui_state_changed=Signal("summary"))
        project_tree = SimpleNamespace(
            itemExpanded=Signal("expanded"),
            itemCollapsed=Signal("collapsed"),
            itemSelectionChanged=Signal("selection"),
        )
        view_stack = SimpleNamespace(currentChanged=Signal("view-stack"))
        takeoff_splitter = SimpleNamespace(splitterMoved=Signal("takeoff-splitter"))
        left_splitter = SimpleNamespace(splitterMoved=Signal("left-splitter"))
        takeoff_sidebar = SimpleNamespace(
            popup_size_changed=Signal("popup"),
            active_page_changed=Signal("active-page"),
        )
        page_settings = SimpleNamespace(dropdown_size_changed=Signal("page-settings"))
        actions = {
            name: SimpleNamespace(toggled=Signal(name))
            for name in (
                "layers",
                "conditions-action",
                "status",
                "mesh",
                "annotation",
                "view",
            )
        }
        plan_view = SimpleNamespace(page_fully_loaded=Signal("page-loaded"))
        shell = SimpleNamespace(
            get_conditions_sidebar=lambda: conditions,
            get_condition_summary_tab=lambda: summary,
            get_project_tree=lambda: project_tree,
            get_view_stack=lambda: view_stack,
            get_takeoff_splitter=lambda: takeoff_splitter,
            get_left_splitter=lambda: left_splitter,
            takeoff_sidebar=takeoff_sidebar,
            get_page_settings_bar=lambda: page_settings,
            get_layers_toggle_action=lambda: actions["layers"],
            get_conditions_toggle_action=lambda: actions["conditions-action"],
            get_status_bar_action=lambda: actions["status"],
            get_mesh_window_action=lambda: actions["mesh"],
            get_annotation_window_action=lambda: actions["annotation"],
            get_view_window_action=lambda: actions["view"],
            get_takeoff_plan_view=lambda: plan_view,
        )
        host = FilterOwner("host")
        toolbar = FilterOwner("toolbar")
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._cleaned_up = False
        coordinator._save_timer = None
        coordinator._host_window = host
        coordinator._tracked_toolbars = (toolbar,)
        coordinator._shell = shell
        coordinator._tracked_detached_windows = {}
        coordinator._tracked_detached_destroy_callbacks = {}
        coordinator._detached_restore_applied = {}
        coordinator.workspace_state_model = object()
        coordinator._state = WorkspaceState()
        with self.assertRaises(ExceptionGroup) as raised:
            coordinator.cleanup()
        self.assertEqual(len(raised.exception.exceptions), 2)
        self.assertEqual(host.attempts, 1)
        self.assertEqual(toolbar.attempts, 1)
        self.assertEqual(len(disconnected), 18)
        self.assertFalse(coordinator._cleaned_up)
        coordinator.cleanup()
        self.assertEqual(host.attempts, 2)
        self.assertEqual(toolbar.attempts, 2)
        self.assertTrue(coordinator._cleaned_up)

    def test_capture_ignores_not_visible_takeoff_splitter_placeholder_sizes(self):
        class CaptureShell:
            def get_takeoff_splitter_sizes(self):
                return [47, 47]

            def get_left_splitter_sizes(self):
                return [12, 12]

            def get_takeoff_splitter(self):
                return _detached_support_FakeSplitterForSidebarSizes(visible=False)

            def get_left_splitter(self):
                return _detached_support_FakeSplitterForSidebarSizes(visible=False)

            def is_conditions_sidebar_visible(self):
                return True

            def is_layers_sidebar_visible(self):
                return True

            def saveGeometry(self):
                return QtCore.QByteArray(b"main-geometry")

            def saveState(self, _version):
                return QtCore.QByteArray(b"main-state")

            def isMaximized(self):
                return False

            def is_status_bar_visible(self):
                return True

            def get_project_expanded_node_keys(self):
                return []

            def is_project_group_by_job_status(self):
                return False

            def get_project_selected_node(self):
                return None

            def get_active_takeoff_view(self):
                return "2d"

            def is_takeoff_2d_tab_visible(self):
                return True

            def is_takeoff_3d_tab_visible(self):
                return True

            def get_workspace_toolbar_visibility_state(self):
                return {}

            def get_takeoff_dropdown_popup_sizes(self):
                return {}

            def get_annotation_styles_by_tool(self):
                return {}

            def is_conditions_group_by_type_enabled(self):
                return True

            def get_summary_grouping(self):
                return ConditionSummaryGrouping(by_type=True, by_area=True)

            def get_mesh_window(self):
                return None

            def get_annotation_window(self):
                return None

            def get_view_window(self):
                return None

        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._shell = CaptureShell()
        coordinator._state = WorkspaceState()
        coordinator._state.takeoff_workspace.left_splitter_sizes = [651, 242]
        coordinator._state.takeoff_workspace.takeoff_splitter_sizes = [360, 1516]
        coordinator.workspace_state_model, _repository = (
            _detached_support__workspace_state_model(coordinator._state)
        )
        coordinator._pending_mesh_restore = False
        coordinator._pending_annotation_restore = False
        coordinator._pending_view_restore = False
        captured = coordinator._capture_current_state()
        self.assertEqual(captured.takeoff_workspace.left_splitter_sizes, [651, 242])
        self.assertEqual(
            captured.takeoff_workspace.takeoff_splitter_sizes,
            [360, 1516],
        )

    def test_capture_persists_summary_header_and_dialog_window_state(self):
        class CaptureShell:
            def get_takeoff_splitter_sizes(self):
                return [300, 700]

            def get_left_splitter_sizes(self):
                return [180, 240]

            def get_takeoff_splitter(self):
                return _detached_support_FakeSplitterForSidebarSizes(visible=True)

            def get_left_splitter(self):
                return _detached_support_FakeSplitterForSidebarSizes(visible=True)

            def is_conditions_sidebar_visible(self):
                return True

            def is_layers_sidebar_visible(self):
                return True

            def saveGeometry(self):
                return QtCore.QByteArray(b"main-geometry")

            def saveState(self, _version):
                return QtCore.QByteArray(b"main-state")

            def isMaximized(self):
                return False

            def is_status_bar_visible(self):
                return True

            def get_project_expanded_node_keys(self):
                return []

            def is_project_group_by_job_status(self):
                return False

            def get_project_selected_node(self):
                return None

            def get_active_takeoff_view(self):
                return "2d"

            def is_takeoff_2d_tab_visible(self):
                return True

            def is_takeoff_3d_tab_visible(self):
                return True

            def get_workspace_toolbar_visibility_state(self):
                return {}

            def get_takeoff_dropdown_popup_sizes(self):
                return {}

            def get_annotation_styles_by_tool(self):
                return {}

            def is_conditions_group_by_type_enabled(self):
                return True

            def get_summary_grouping(self):
                return ConditionSummaryGrouping(
                    by_page=True,
                    by_type=False,
                    by_area=True,
                )

            def get_mesh_window(self):
                return None

            def get_annotation_window(self):
                return None

            def get_view_window(self):
                return None

        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._shell = CaptureShell()
        coordinator._state = WorkspaceState()
        coordinator._state.header_layouts["condition_summary"] = HeaderLayoutState(
            widths={"name": 222, "area": 145},
            order=["name", "area"],
            sort_column="name",
        )
        coordinator.workspace_state_model, repository = (
            _detached_support__workspace_state_model(coordinator._state)
        )
        current_state = coordinator.workspace_state_model.state
        current_state.dialog_sizes["cover_sheet"] = [760, 560]
        current_state.dialog_maximized["cover_sheet"] = True
        coordinator.workspace_state_model.update_state(current_state)
        coordinator._pending_mesh_restore = False
        coordinator._pending_annotation_restore = False
        coordinator._pending_view_restore = False
        captured = coordinator._capture_current_state()
        self.assertTrue(captured.takeoff_workspace.summary_group_by_page)
        self.assertFalse(captured.takeoff_workspace.summary_group_by_type)
        self.assertTrue(captured.takeoff_workspace.summary_group_by_area)
        self.assertEqual(
            captured.header_layouts["condition_summary"].widths,
            {"name": 222, "area": 145},
        )
        self.assertEqual(captured.dialog_sizes, {"cover_sheet": [760, 560]})
        self.assertEqual(captured.dialog_maximized, {"cover_sheet": True})
        coordinator.workspace_state_model.update_state(captured)
        reloaded = WorkspaceStateAggregate(repository).state
        self.assertEqual(reloaded.dialog_sizes, {"cover_sheet": [760, 560]})
        self.assertEqual(reloaded.dialog_maximized, {"cover_sheet": True})

    def test_restore_applies_summary_grouping_without_owning_header_layout(self):
        class Shell:
            def __init__(self):
                self.summary_grouping = None

            def set_conditions_group_by_type(self, _enabled):
                pass

            def set_summary_grouping(self, grouping):
                self.summary_grouping = grouping

        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._shell = Shell()
        coordinator._state = WorkspaceState()
        coordinator._state.takeoff_workspace.summary_group_by_page = True
        coordinator._state.takeoff_workspace.summary_group_by_type = False
        coordinator._state.takeoff_workspace.summary_group_by_area = True
        coordinator._restore_takeoff_sidebar_state()
        self.assertEqual(
            coordinator._shell.summary_grouping,
            ConditionSummaryGrouping(by_page=True, by_type=False, by_area=True),
        )

    def test_hidden_layer_sidebar_capture_keeps_last_valid_splitter_layout(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)

        class Shell:
            def is_conditions_sidebar_visible(self):
                return True

            def is_layers_sidebar_visible(self):
                return False

        coordinator._shell = Shell()
        self.assertEqual(
            coordinator._preserve_hidden_splitter_sizes([600, 0], [220, 380]),
            [220, 380],
        )

    def test_hidden_condition_sidebar_capture_keeps_last_valid_splitter_layout(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)

        class Shell:
            def is_conditions_sidebar_visible(self):
                return False

            def is_layers_sidebar_visible(self):
                return True

        coordinator._shell = Shell()
        self.assertEqual(
            coordinator._preserve_hidden_splitter_sizes([0, 600], [220, 380]),
            [220, 380],
        )

    def test_hidden_sidebars_capture_keeps_last_valid_splitter_layout(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)

        class Shell:
            def is_conditions_sidebar_visible(self):
                return False

            def is_layers_sidebar_visible(self):
                return False

        coordinator._shell = Shell()
        self.assertEqual(
            coordinator._preserve_hidden_splitter_sizes([600, 0], [220, 380]),
            [220, 380],
        )

    def test_visible_sidebars_capture_uses_current_splitter_layout(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)

        class Shell:
            def is_conditions_sidebar_visible(self):
                return True

            def is_layers_sidebar_visible(self):
                return True

        coordinator._shell = Shell()
        self.assertEqual(
            coordinator._preserve_hidden_splitter_sizes([260, 340], [220, 380]),
            [260, 340],
        )

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
        state.geometry_b64 = _detached_support__encoded_geometry()
        state.is_maximized = is_maximized
        coordinator._state.takeoff_workspace.dropdown_popup_sizes = {
            "annotation_page": [320, 360],
            "annotation_scale": [517, 413],
        }
        return coordinator

    def test_auto_restore_annotation_window_passes_fullscreen_state(self):
        calls = []

        class Shell:
            def can_restore_annotation_window(self):
                return True

            def is_annotation_window_open(self):
                return True

            def set_annotation_window_visible(
                self,
                visible,
                *,
                initial_geometry=None,
                initial_is_maximized=False,
                initial_is_fullscreen=False,
            ):
                calls.append(
                    (
                        visible,
                        initial_geometry,
                        initial_is_maximized,
                        initial_is_fullscreen,
                    )
                )

        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._pending_annotation_restore = True
        coordinator._takeoff_workspace_ready = True
        coordinator._state = WorkspaceState()
        state = coordinator._state.detached_windows.annotation_view
        state.geometry_b64 = _detached_support__encoded_geometry()
        state.is_maximized = False
        state.is_fullscreen = True
        coordinator._decode_byte_array = WorkspaceStateCoordinator._decode_byte_array
        coordinator._schedule_track_detached_window = lambda _key: None
        coordinator._shell = Shell()
        coordinator._try_restore_annotation_window()
        self.assertFalse(coordinator._pending_annotation_restore)
        self.assertEqual(calls[0], (True, QtCore.QByteArray(b"geometry"), False, True))

    def test_auto_restore_view_window_passes_fullscreen_state(self):
        calls = []

        class Shell:
            def can_restore_view_window(self):
                return True

            def is_view_window_open(self):
                return True

            def set_view_window_visible(
                self,
                visible,
                *,
                initial_geometry=None,
                initial_is_maximized=False,
                initial_is_fullscreen=False,
            ):
                calls.append(
                    (
                        visible,
                        initial_geometry,
                        initial_is_maximized,
                        initial_is_fullscreen,
                    )
                )

        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._pending_view_restore = True
        coordinator._takeoff_workspace_ready = True
        coordinator._state = WorkspaceState()
        state = coordinator._state.detached_windows.view_window
        state.geometry_b64 = _detached_support__encoded_geometry()
        state.is_maximized = False
        state.is_fullscreen = True
        coordinator._decode_byte_array = WorkspaceStateCoordinator._decode_byte_array
        coordinator._schedule_track_detached_window = lambda _key: None
        coordinator._shell = Shell()
        coordinator._try_restore_view_window()
        self.assertFalse(coordinator._pending_view_restore)
        self.assertEqual(calls[0], (True, QtCore.QByteArray(b"geometry"), False, True))

    def test_detached_window_state_persists_fullscreen_flag(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        window = _detached_support_FakeDetachedWindow(fullscreen=True)
        window.saveGeometry = lambda: QtCore.QByteArray(b"fullscreen")
        state = coordinator._capture_detached_window_state(
            WorkspaceState().detached_windows.annotation_view,
            window,
            is_open=True,
        )
        self.assertTrue(state.open)
        self.assertTrue(state.is_fullscreen)
        self.assertFalse(state.is_maximized)

    def test_saved_mesh_windowed_state_restores_geometry_without_maximizing(self):
        window = _detached_support_FakeDetachedWindow(visible=True, maximized=True)
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
        window = _detached_support_FakeDetachedWindow(visible=True, maximized=False)
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
        window = _detached_support_FakeDetachedWindow(visible=False)
        coordinator = self._coordinator_for_window(
            window,
            key=WorkspaceStateCoordinator._DETACHED_MESH,
            is_maximized=False,
        )
        coordinator._apply_saved_mesh_window_state(window)
        self.assertEqual(window.initial_states, [(b"geometry", False)])
        self.assertEqual(window.show_maximized_calls, 0)

    def test_tracked_page_window_keeps_pre_show_geometry(self):
        window = _detached_support_FakeDetachedWindow(visible=True, maximized=True)
        coordinator = self._coordinator_for_window(window, is_maximized=False)
        coordinator._complete_detached_window_tracking(
            WorkspaceStateCoordinator._DETACHED_ANNOTATION,
            window,
        )
        self.assertEqual(window.initial_states, [])
        self.assertEqual(window.restored_geometries, [])
        self.assertEqual(window.show_normal_calls, 0)
        self.assertEqual(window.show_maximized_calls, 0)
        self.assertEqual(
            window.dropdown_sizes,
            {"annotation_page": [320, 360], "annotation_scale": [517, 413]},
        )

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
        timer = _detached_support_FakeWorkspaceSaveTimer(active=False)
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

    def test_late_initial_detached_restore_after_cleanup_is_ignored(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._cleaned_up = True
        coordinator._state = None
        coordinator._shell = None
        coordinator.restore_deferred_state()

    def test_initial_detached_restore_still_runs_before_cleanup(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._cleaned_up = False
        coordinator._state = WorkspaceState()
        coordinator._state.detached_windows.mesh_view.open = True
        coordinator._state.detached_windows.annotation_view.open = True
        coordinator._state.detached_windows.view_window.open = True
        calls = []
        coordinator._try_restore_mesh_window = lambda: calls.append("mesh")
        coordinator._try_restore_detached_page_windows = lambda: calls.append("pages")
        coordinator.restore_deferred_state()
        self.assertTrue(coordinator._pending_mesh_restore)
        self.assertTrue(coordinator._pending_annotation_restore)
        self.assertTrue(coordinator._pending_view_restore)
        self.assertEqual(calls, ["mesh", "pages"])

    def test_late_detached_tracking_after_cleanup_is_ignored(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._cleaned_up = True
        coordinator._track_detached_window(WorkspaceStateCoordinator._DETACHED_VIEW)

    def test_late_splitter_restore_after_cleanup_is_ignored(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._cleaned_up = True
        coordinator._shell = None
        coordinator._restore_takeoff_splitter_sizes_after_show([100, 200])
        coordinator._restore_left_splitter_sizes_after_show([30, 70])

    def test_reset_to_defaults_persists_default_workspace_and_reapplies_state(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        timer = _detached_support_FakeWorkspaceSaveTimer(active=True)
        model, repository = _detached_support__workspace_state_model()
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
        self.assertEqual(repository.saved_states, [WorkspaceState()])
        self.assertEqual(coordinator._state, WorkspaceState())
        self.assertEqual(coordinator._pending_takeoff_splitter_sizes, [])
        self.assertEqual(coordinator._pending_splitter_sizes, [])
        self.assertFalse(coordinator._pending_mesh_restore)
        self.assertFalse(coordinator._pending_annotation_restore)
        self.assertFalse(coordinator._pending_view_restore)
        self.assertEqual(restored, ["restore"])

    def test_untracking_detached_window_releases_filters_and_callbacks(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        window = _detached_support_TrackableDetachedWindow()
        callback = lambda *_args: None
        key = WorkspaceStateCoordinator._DETACHED_ANNOTATION
        coordinator._tracked_detached_destroy_callbacks = {key: callback}
        window.installEventFilter(coordinator)
        window.dropdown_size_changed.connect(coordinator._on_dropdown_size_changed)
        window.destroyed.connect(callback)
        coordinator._untrack_detached_window(key, window)
        self.assertEqual(window.installed_filters, [])
        self.assertEqual(
            window.dropdown_size_changed.disconnected,
            [coordinator._on_dropdown_size_changed],
        )
        self.assertEqual(window.destroyed.disconnected, [callback])
        self.assertEqual(coordinator._tracked_detached_destroy_callbacks, {})

    def test_detached_dropdown_resize_caches_sizes_before_debounced_save(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        timer = _detached_support_FakeWorkspaceSaveTimer(active=False)
        coordinator._cleaned_up = False
        coordinator._save_timer = timer
        coordinator._state = WorkspaceState()
        coordinator._state.takeoff_workspace.dropdown_popup_sizes = {
            "annotation_page": [320, 360]
        }
        coordinator._shell = SimpleNamespace(
            get_takeoff_dropdown_popup_sizes=lambda: {
                "annotation_page": [0, 360],
                "annotation_named_views": [640, 420],
                "annotation_scale": [517, 413],
                "view_page": [700, 500],
                "view_named_views": [710, 510],
                "unknown_popup": [900, 900],
            }
        )
        coordinator._on_dropdown_size_changed()
        self.assertTrue(timer.started)
        self.assertEqual(
            coordinator._state.takeoff_workspace.dropdown_popup_sizes,
            {
                "annotation_page": [320, 360],
                "annotation_named_views": [640, 420],
                "annotation_scale": [517, 413],
                "view_page": [700, 500],
                "view_named_views": [710, 510],
            },
        )

    def test_detached_dropdown_sizes_survive_closed_window_state_capture(self):
        class CaptureShell:
            def __init__(self):
                self.dropdown_sizes = {"main_page": [220, 330]}

            def get_takeoff_splitter_sizes(self):
                return [300, 700]

            def get_left_splitter_sizes(self):
                return [180, 240]

            def is_conditions_sidebar_visible(self):
                return True

            def is_layers_sidebar_visible(self):
                return True

            def saveGeometry(self):
                return QtCore.QByteArray(b"main-geometry")

            def saveState(self, _version):
                return QtCore.QByteArray(b"main-state")

            def isMaximized(self):
                return False

            def is_status_bar_visible(self):
                return True

            def get_project_expanded_node_keys(self):
                return []

            def is_project_group_by_job_status(self):
                return False

            def get_project_selected_node(self):
                return None

            def get_active_takeoff_view(self):
                return "2d"

            def is_takeoff_2d_tab_visible(self):
                return True

            def is_takeoff_3d_tab_visible(self):
                return True

            def get_workspace_toolbar_visibility_state(self):
                return {}

            def get_takeoff_dropdown_popup_sizes(self):
                return dict(self.dropdown_sizes)

            def get_annotation_styles_by_tool(self):
                return {}

            def is_conditions_group_by_type_enabled(self):
                return True

            def get_summary_grouping(self):
                return ConditionSummaryGrouping(by_type=True, by_area=True)

            def get_mesh_window(self):
                return None

            def get_annotation_window(self):
                return None

            def get_view_window(self):
                return None

        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._shell = CaptureShell()
        coordinator._state = WorkspaceState()
        coordinator._pending_mesh_restore = False
        coordinator._pending_annotation_restore = False
        coordinator._pending_view_restore = False
        coordinator._state.takeoff_workspace.dropdown_popup_sizes = {
            "annotation_page": [640, 420],
            "annotation_named_views": [650, 430],
            "view_page": [700, 500],
            "view_named_views": [710, 510],
        }
        coordinator.workspace_state_model, _repository = (
            _detached_support__workspace_state_model(coordinator._state)
        )
        captured = coordinator._capture_current_state()
        self.assertEqual(
            captured.takeoff_workspace.dropdown_popup_sizes,
            {
                "annotation_page": [640, 420],
                "annotation_named_views": [650, 430],
                "view_page": [700, 500],
                "view_named_views": [710, 510],
                "main_page": [220, 330],
            },
        )

    def test_tracked_window_destroy_drops_matching_reference(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        key = WorkspaceStateCoordinator._DETACHED_VIEW
        window = _detached_support_TrackableDetachedWindow()
        coordinator._tracked_detached_windows = {key: window}
        coordinator._tracked_detached_destroy_callbacks = {key: lambda *_args: None}
        coordinator._detached_restore_applied = {key: True}
        coordinator._save_timer = None
        coordinator._cleaned_up = False
        coordinator._on_tracked_window_destroyed(key, window)
        self.assertEqual(coordinator._tracked_detached_windows, {})
        self.assertEqual(coordinator._tracked_detached_destroy_callbacks, {})
        self.assertEqual(coordinator._detached_restore_applied, {})

    def test_stale_window_destroy_keeps_replacement_tracking(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        key = WorkspaceStateCoordinator._DETACHED_VIEW
        stale_window = _detached_support_TrackableDetachedWindow()
        replacement_window = _detached_support_TrackableDetachedWindow()
        callback = lambda *_args: None
        coordinator._tracked_detached_windows = {key: replacement_window}
        coordinator._tracked_detached_destroy_callbacks = {key: callback}
        coordinator._detached_restore_applied = {key: True}
        coordinator._save_timer = None
        coordinator._cleaned_up = False
        coordinator._on_tracked_window_destroyed(key, stale_window)
        self.assertIs(coordinator._tracked_detached_windows[key], replacement_window)
        self.assertIs(coordinator._tracked_detached_destroy_callbacks[key], callback)
        self.assertTrue(coordinator._detached_restore_applied[key])


class DetachedPageViewManagerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        cls.app.processEvents()

    def test_main_and_annotation_scale_popup_sizes_persist_independently(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        merged = coordinator._merge_dropdown_popup_sizes(
            {"main_scale": [320, 360], "annotation_scale": [420, 380]},
            {"annotation_scale": [517, 413]},
        )
        self.assertEqual(
            merged,
            {"main_scale": [320, 360], "annotation_scale": [517, 413]},
        )
