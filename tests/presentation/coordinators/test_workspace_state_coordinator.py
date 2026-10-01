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
    DetachedWindowState,
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


class _SplitterCaptureShell:
    """Shell double for state capture with configurable splitter geometry."""

    def __init__(
        self,
        *,
        takeoff_sizes,
        left_sizes,
        takeoff_visible=True,
        left_visible=True,
        conditions_visible=True,
        layers_visible=True,
        summary_grouping=None,
    ):
        self._summary_grouping = summary_grouping or ConditionSummaryGrouping(
            by_type=True, by_area=True
        )
        self._takeoff_sizes = takeoff_sizes
        self._left_sizes = left_sizes
        self._takeoff_visible = takeoff_visible
        self._left_visible = left_visible
        self._conditions_visible = conditions_visible
        self._layers_visible = layers_visible

    def get_takeoff_splitter_sizes(self):
        return list(self._takeoff_sizes)

    def get_left_splitter_sizes(self):
        return list(self._left_sizes)

    def get_takeoff_splitter(self):
        return _detached_support_FakeSplitterForSidebarSizes(
            visible=self._takeoff_visible
        )

    def get_left_splitter(self):
        return _detached_support_FakeSplitterForSidebarSizes(visible=self._left_visible)

    def is_conditions_sidebar_visible(self):
        return self._conditions_visible

    def is_layers_sidebar_visible(self):
        return self._layers_visible

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
        return self._summary_grouping

    def get_mesh_window(self):
        return None

    def get_annotation_window(self):
        return None

    def get_view_window(self):
        return None


def _capture_coordinator(shell, previous_takeoff_sizes, previous_left_sizes):
    coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
    coordinator._shell = shell
    coordinator._state = WorkspaceState()
    coordinator._state.takeoff_workspace.takeoff_splitter_sizes = list(
        previous_takeoff_sizes
    )
    coordinator._state.takeoff_workspace.left_splitter_sizes = list(previous_left_sizes)
    coordinator.workspace_state_model, _repository = (
        _detached_support__workspace_state_model(coordinator._state)
    )
    coordinator._pending_mesh_restore = False
    coordinator._pending_annotation_restore = False
    coordinator._pending_view_restore = False
    return coordinator


_CLEANUP_SIGNAL_NAMES = (
    "conditions",
    "summary",
    "expanded",
    "collapsed",
    "selection",
    "view-stack",
    "takeoff-splitter",
    "left-splitter",
    "popup",
    "page-settings",
    "layers",
    "conditions-action",
    "status",
    "mesh",
    "annotation",
    "view",
    "active-page",
    "page-loaded",
)


def _build_cleanup_coordinator(failing_filter_attempts=1):
    """Coordinator whose tracked signals/filter owners record cleanup calls."""
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
            if self.attempts <= failing_filter_attempts:
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
    return SimpleNamespace(
        coordinator=coordinator,
        disconnected=disconnected,
        host=host,
        toolbar=toolbar,
        shell=shell,
    )


class WorkspaceStateDecodeTests(unittest.TestCase):
    def test_decode_byte_array_rejects_corrupted_non_string_state(self):
        decoded = WorkspaceStateCoordinator._decode_byte_array(123)
        self.assertTrue(decoded.isEmpty())

    def test_decode_byte_array_handles_empty_non_ascii_and_valid_state(self):
        for value in (None, "", "café"):
            with self.subTest(value=value):
                decoded = WorkspaceStateCoordinator._decode_byte_array(value)
                self.assertTrue(decoded.isEmpty())
        decoded = WorkspaceStateCoordinator._decode_byte_array(
            _detached_support__encoded_geometry(b"payload")
        )
        self.assertEqual(bytes(decoded), b"payload")
        self.assertIsNone(
            WorkspaceStateCoordinator._encode_byte_array(QtCore.QByteArray())
        )


class WorkspaceStateCoordinatorDetachedWindowTests(unittest.TestCase):
    def test_workspace_cleanup_attempts_all_stages_and_retries_failures(self):
        fixture = _build_cleanup_coordinator(failing_filter_attempts=1)
        coordinator = fixture.coordinator
        with self.assertRaises(ExceptionGroup) as raised:
            coordinator.cleanup()
        self.assertEqual(
            sorted(str(error) for error in raised.exception.exceptions),
            ["host failed", "toolbar failed"],
        )
        self.assertEqual(fixture.host.attempts, 1)
        self.assertEqual(fixture.toolbar.attempts, 1)
        self.assertEqual(sorted(fixture.disconnected), sorted(_CLEANUP_SIGNAL_NAMES))
        self.assertFalse(coordinator._cleaned_up)
        self.assertIs(coordinator._shell, fixture.shell)
        self.assertIs(coordinator._host_window, fixture.host)
        coordinator.cleanup()
        self.assertEqual(fixture.host.attempts, 2)
        self.assertEqual(fixture.toolbar.attempts, 2)
        self.assertTrue(coordinator._cleaned_up)
        self.assertIsNone(coordinator._shell)
        self.assertIsNone(coordinator._host_window)
        self.assertIsNone(coordinator._state)
        self.assertIsNone(coordinator.workspace_state_model)
        self.assertEqual(coordinator._tracked_toolbars, ())
        disconnects_after_cleanup = len(fixture.disconnected)
        coordinator.cleanup()
        self.assertEqual(fixture.host.attempts, 2)
        self.assertEqual(len(fixture.disconnected), disconnects_after_cleanup)

    def test_workspace_cleanup_continues_after_a_failing_disconnect_stage(self):
        fixture = _build_cleanup_coordinator(failing_filter_attempts=0)
        coordinator = fixture.coordinator
        healthy_sidebar_accessor = fixture.shell.get_conditions_sidebar

        def broken_sidebar():
            raise RuntimeError("sidebar gone")

        fixture.shell.get_conditions_sidebar = broken_sidebar
        with self.assertRaises(ExceptionGroup) as raised:
            coordinator.cleanup()
        self.assertEqual(
            [str(error) for error in raised.exception.exceptions], ["sidebar gone"]
        )
        self.assertEqual(
            sorted(fixture.disconnected),
            sorted(name for name in _CLEANUP_SIGNAL_NAMES if name != "conditions"),
        )
        self.assertEqual(fixture.host.attempts, 1)
        self.assertEqual(fixture.toolbar.attempts, 1)
        self.assertFalse(coordinator._cleaned_up)
        fixture.shell.get_conditions_sidebar = healthy_sidebar_accessor
        coordinator.cleanup()
        self.assertTrue(coordinator._cleaned_up)
        self.assertIn("conditions", fixture.disconnected)

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

    def test_capture_maps_each_summary_grouping_flag_independently(self):
        for flag in ("by_page", "by_type", "by_area"):
            with self.subTest(only=flag):
                grouping = ConditionSummaryGrouping(**{flag: True})
                coordinator = _capture_coordinator(
                    _SplitterCaptureShell(
                        takeoff_sizes=[300, 700],
                        left_sizes=[180, 240],
                        summary_grouping=grouping,
                    ),
                    previous_takeoff_sizes=[],
                    previous_left_sizes=[],
                )
                workspace = coordinator._capture_current_state().takeoff_workspace
                self.assertEqual(
                    (
                        workspace.summary_group_by_page,
                        workspace.summary_group_by_type,
                        workspace.summary_group_by_area,
                    ),
                    (flag == "by_page", flag == "by_type", flag == "by_area"),
                )

    def test_capture_uses_visible_splitter_sizes(self):
        coordinator = _capture_coordinator(
            _SplitterCaptureShell(takeoff_sizes=[300, 700], left_sizes=[180, 240]),
            previous_takeoff_sizes=[360, 1516],
            previous_left_sizes=[651, 242],
        )
        captured = coordinator._capture_current_state()
        self.assertEqual(captured.takeoff_workspace.takeoff_splitter_sizes, [300, 700])
        self.assertEqual(captured.takeoff_workspace.left_splitter_sizes, [180, 240])

    def test_capture_keeps_previous_sizes_when_visible_splitter_reports_zero_total(
        self,
    ):
        coordinator = _capture_coordinator(
            _SplitterCaptureShell(takeoff_sizes=[0, 0], left_sizes=[0, 0]),
            previous_takeoff_sizes=[360, 1516],
            previous_left_sizes=[651, 242],
        )
        captured = coordinator._capture_current_state()
        self.assertEqual(captured.takeoff_workspace.takeoff_splitter_sizes, [360, 1516])
        self.assertEqual(captured.takeoff_workspace.left_splitter_sizes, [651, 242])

    def test_capture_without_previous_sizes_records_current_hidden_splitter_sizes(
        self,
    ):
        coordinator = _capture_coordinator(
            _SplitterCaptureShell(
                takeoff_sizes=[47, 47],
                left_sizes=[12, 12],
                takeoff_visible=False,
                left_visible=False,
            ),
            previous_takeoff_sizes=[],
            previous_left_sizes=[],
        )
        captured = coordinator._capture_current_state()
        self.assertEqual(captured.takeoff_workspace.takeoff_splitter_sizes, [47, 47])
        self.assertEqual(captured.takeoff_workspace.left_splitter_sizes, [12, 12])

    def test_capture_restores_collapsed_takeoff_pane_when_both_sidebars_hidden(self):
        coordinator = _capture_coordinator(
            _SplitterCaptureShell(
                takeoff_sizes=[0, 1900],
                left_sizes=[651, 242],
                conditions_visible=False,
                layers_visible=False,
            ),
            previous_takeoff_sizes=[360, 1516],
            previous_left_sizes=[651, 242],
        )
        captured = coordinator._capture_current_state()
        self.assertEqual(captured.takeoff_workspace.takeoff_splitter_sizes, [360, 1900])
        self.assertFalse(captured.takeoff_workspace.conditions_sidebar_visible)
        self.assertFalse(captured.takeoff_workspace.layers_sidebar_visible)

    def test_hidden_takeoff_splitter_preservation_only_fills_collapsed_first_pane(
        self,
    ):
        cases = (
            (
                "both hidden, collapsed",
                False,
                False,
                [0, 1500],
                [360, 1516],
                [360, 1500],
            ),
            ("conditions visible", True, False, [0, 1500], [360, 1516], [0, 1500]),
            ("layers visible", False, True, [0, 1500], [360, 1516], [0, 1500]),
            ("both hidden, open", False, False, [200, 1500], [360, 1516], [200, 1500]),
            ("no previous layout", False, False, [0, 1500], [], [0, 1500]),
            ("negative clamped", True, True, [-5, 1500], [360, 1516], [0, 1500]),
        )
        for label, conditions, layers, current, previous, expected in cases:
            with self.subTest(label):
                coordinator = WorkspaceStateCoordinator.__new__(
                    WorkspaceStateCoordinator
                )
                coordinator._shell = _SplitterCaptureShell(
                    takeoff_sizes=[],
                    left_sizes=[],
                    conditions_visible=conditions,
                    layers_visible=layers,
                )
                self.assertEqual(
                    coordinator._preserve_hidden_takeoff_splitter_sizes(
                        current, previous
                    ),
                    expected,
                )

    def test_hidden_sidebar_preservation_ignores_unusable_previous_layout(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._shell = _SplitterCaptureShell(
            takeoff_sizes=[],
            left_sizes=[],
            conditions_visible=False,
            layers_visible=True,
        )
        for previous in ([], [220], [0, 380], [220, 0]):
            with self.subTest(previous=previous):
                self.assertEqual(
                    coordinator._preserve_hidden_splitter_sizes([0, 600], previous),
                    [0, 600],
                )
        self.assertEqual(
            coordinator._preserve_hidden_splitter_sizes([0, 600], [220, 380, 40]),
            [220, 380],
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
        self.assertEqual(
            captured.header_layouts["condition_summary"].order, ["name", "area"]
        )
        self.assertEqual(
            captured.header_layouts["condition_summary"].sort_column, "name"
        )
        self.assertEqual(captured.dialog_sizes, {"cover_sheet": [760, 560]})
        self.assertEqual(captured.dialog_maximized, {"cover_sheet": True})
        coordinator.workspace_state_model.update_state(captured)
        reloaded = WorkspaceStateAggregate(repository).state
        self.assertEqual(reloaded.dialog_sizes, {"cover_sheet": [760, 560]})
        self.assertEqual(reloaded.dialog_maximized, {"cover_sheet": True})
        self.assertEqual(
            reloaded.header_layouts["condition_summary"].widths,
            {"name": 222, "area": 145},
        )
        self.assertTrue(reloaded.takeoff_workspace.summary_group_by_page)
        self.assertFalse(reloaded.takeoff_workspace.summary_group_by_type)

    def test_restore_applies_summary_grouping_without_owning_header_layout(self):
        class Shell:
            def __init__(self):
                self.summary_grouping = None
                self.conditions_group_by_type = None

            def set_conditions_group_by_type(self, enabled):
                self.conditions_group_by_type = enabled

            def set_summary_grouping(self, grouping):
                self.summary_grouping = grouping

        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._shell = Shell()
        coordinator._state = WorkspaceState()
        coordinator._state.takeoff_workspace.conditions_group_by_type = False
        coordinator._state.takeoff_workspace.summary_group_by_page = True
        coordinator._state.takeoff_workspace.summary_group_by_type = False
        coordinator._state.takeoff_workspace.summary_group_by_area = True
        coordinator._restore_takeoff_sidebar_state()
        self.assertEqual(
            coordinator._shell.summary_grouping,
            ConditionSummaryGrouping(by_page=True, by_type=False, by_area=True),
        )
        self.assertIs(coordinator._shell.conditions_group_by_type, False)

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

    def _page_window_restore_coordinator(
        self, kind, *, pending=True, ready=True, can_restore=True, opens=True
    ):
        calls = []
        tracked = []

        class Shell:
            def can_restore_annotation_window(self):
                return can_restore

            def can_restore_view_window(self):
                return can_restore

            def is_annotation_window_open(self):
                return opens

            def is_view_window_open(self):
                return opens

            def set_annotation_window_visible(self, visible, **options):
                calls.append(("annotation", visible, options))

            def set_view_window_visible(self, visible, **options):
                calls.append(("view", visible, options))

        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._pending_annotation_restore = pending and kind == "annotation"
        coordinator._pending_view_restore = pending and kind == "view"
        coordinator._takeoff_workspace_ready = ready
        coordinator._state = WorkspaceState()
        window_state = (
            coordinator._state.detached_windows.annotation_view
            if kind == "annotation"
            else coordinator._state.detached_windows.view_window
        )
        window_state.geometry_b64 = _detached_support__encoded_geometry()
        window_state.is_maximized = True
        coordinator._schedule_track_detached_window = tracked.append
        coordinator._shell = Shell()
        return coordinator, calls, tracked

    def test_page_window_auto_restore_is_gated_on_pending_ready_and_restorable(self):
        for kind in ("annotation", "view"):
            attempt = lambda coordinator, kind=kind: (
                coordinator._try_restore_annotation_window()
                if kind == "annotation"
                else coordinator._try_restore_view_window()
            )
            pending_attr = f"_pending_{kind}_restore"
            for label, options in (
                ("not pending", {"pending": False}),
                ("workspace not ready", {"ready": False}),
                ("shell cannot restore", {"can_restore": False}),
            ):
                with self.subTest(kind=kind, gate=label):
                    coordinator, calls, tracked = self._page_window_restore_coordinator(
                        kind, **options
                    )
                    attempt(coordinator)
                    self.assertEqual(calls, [])
                    self.assertEqual(tracked, [])
                    self.assertEqual(
                        getattr(coordinator, pending_attr), options.get("pending", True)
                    )

    def test_page_window_auto_restore_keeps_pending_when_window_does_not_open(self):
        for kind in ("annotation", "view"):
            with self.subTest(kind=kind):
                coordinator, calls, tracked = self._page_window_restore_coordinator(
                    kind, opens=False
                )
                if kind == "annotation":
                    coordinator._try_restore_annotation_window()
                    still_pending = coordinator._pending_annotation_restore
                else:
                    coordinator._try_restore_view_window()
                    still_pending = coordinator._pending_view_restore
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][:2], (kind, True))
                self.assertTrue(calls[0][2]["initial_is_maximized"])
                self.assertFalse(calls[0][2]["initial_is_fullscreen"])
                self.assertTrue(still_pending)
                self.assertEqual(tracked, [])

    def test_page_window_auto_restore_tracks_window_after_it_opens(self):
        for kind, key in (
            ("annotation", WorkspaceStateCoordinator._DETACHED_ANNOTATION),
            ("view", WorkspaceStateCoordinator._DETACHED_VIEW),
        ):
            with self.subTest(kind=kind):
                coordinator, calls, tracked = self._page_window_restore_coordinator(
                    kind
                )
                if kind == "annotation":
                    coordinator._try_restore_annotation_window()
                else:
                    coordinator._try_restore_view_window()
                self.assertEqual(tracked, [key])
                self.assertEqual(len(calls), 1)
                self.assertEqual(
                    calls[0][2]["initial_geometry"], QtCore.QByteArray(b"geometry")
                )

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
        self.assertEqual(
            state.geometry_b64, _detached_support__encoded_geometry(b"fullscreen")
        )

    def test_hidden_or_missing_detached_window_capture_keeps_previous_state(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        previous = DetachedWindowState(
            open=False,
            geometry_b64=_detached_support__encoded_geometry(b"saved"),
            is_maximized=True,
            is_fullscreen=False,
        )
        hidden = _detached_support_FakeDetachedWindow(
            visible=False, maximized=False, fullscreen=True
        )
        hidden.saveGeometry = lambda: QtCore.QByteArray(b"transient")
        for label, window in (("hidden", hidden), ("missing", None)):
            with self.subTest(label):
                captured = coordinator._capture_detached_window_state(
                    previous, window, is_open=True
                )
                self.assertTrue(captured.open)
                self.assertEqual(
                    captured.geometry_b64, _detached_support__encoded_geometry(b"saved")
                )
                self.assertTrue(captured.is_maximized)
                self.assertFalse(captured.is_fullscreen)

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
        self.assertEqual(
            coordinator._detached_restore_applied,
            {WorkspaceStateCoordinator._DETACHED_MESH: True},
        )

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
        self.assertEqual(
            coordinator._detached_restore_applied,
            {WorkspaceStateCoordinator._DETACHED_MESH: True},
        )

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
        self.assertEqual(window.restored_geometries, [])
        self.assertEqual(
            coordinator._detached_restore_applied,
            {WorkspaceStateCoordinator._DETACHED_MESH: True},
        )

    def test_hidden_mesh_window_receives_saved_maximized_flag_before_show(self):
        window = _detached_support_FakeDetachedWindow(visible=False)
        coordinator = self._coordinator_for_window(
            window,
            key=WorkspaceStateCoordinator._DETACHED_MESH,
            is_maximized=True,
        )
        coordinator._apply_saved_mesh_window_state(window)
        self.assertEqual(window.initial_states, [(b"geometry", True)])
        self.assertEqual(window.show_maximized_calls, 0)

    def test_untracked_mesh_window_state_is_not_applied(self):
        tracked = _detached_support_FakeDetachedWindow(visible=True)
        stale = _detached_support_FakeDetachedWindow(visible=True, maximized=True)
        coordinator = self._coordinator_for_window(
            tracked,
            key=WorkspaceStateCoordinator._DETACHED_MESH,
            is_maximized=True,
        )
        coordinator._apply_saved_mesh_window_state(stale)
        self.assertEqual(stale.restored_geometries, [])
        self.assertEqual(stale.initial_states, [])
        self.assertEqual(stale.show_maximized_calls, 0)
        self.assertEqual(coordinator._detached_restore_applied, {})

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
        self.assertEqual(
            coordinator._detached_restore_applied,
            {WorkspaceStateCoordinator._DETACHED_ANNOTATION: True},
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

    def test_request_save_starts_debounce_timer_before_cleanup(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        timer = _detached_support_FakeWorkspaceSaveTimer(active=False)
        coordinator._cleaned_up = False
        coordinator._save_timer = timer
        coordinator.request_save("ignored", 3)
        self.assertTrue(timer.started)
        coordinator._save_timer = None
        coordinator.request_save()

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

    def test_deferred_view_restore_requires_the_annotation_window_to_be_open(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._cleaned_up = False
        coordinator._state = WorkspaceState()
        coordinator._state.detached_windows.view_window.open = True
        coordinator._try_restore_mesh_window = lambda: None
        coordinator._try_restore_detached_page_windows = lambda: None
        coordinator.restore_deferred_state()
        self.assertFalse(coordinator._pending_mesh_restore)
        self.assertFalse(coordinator._pending_annotation_restore)
        self.assertFalse(coordinator._pending_view_restore)
        coordinator._state.detached_windows.annotation_view.open = True
        coordinator.restore_deferred_state()
        self.assertFalse(coordinator._pending_mesh_restore)
        self.assertTrue(coordinator._pending_annotation_restore)
        self.assertTrue(coordinator._pending_view_restore)

    def test_late_detached_tracking_after_cleanup_is_ignored(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._cleaned_up = True
        lookups = []
        coordinator._shell = SimpleNamespace(
            get_view_window=lambda: lookups.append("view") or object()
        )
        coordinator._tracked_detached_windows = {}
        coordinator._track_detached_window(WorkspaceStateCoordinator._DETACHED_VIEW)
        self.assertEqual(lookups, [])
        self.assertEqual(coordinator._tracked_detached_windows, {})

    def test_late_splitter_restore_after_cleanup_is_ignored(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._cleaned_up = True
        coordinator._shell = None
        coordinator._restore_takeoff_splitter_sizes_after_show([100, 200])
        coordinator._restore_left_splitter_sizes_after_show([30, 70])

    def test_splitter_restore_after_show_applies_sizes_before_cleanup(self):
        calls = []
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        coordinator._cleaned_up = False
        coordinator._shell = SimpleNamespace(
            set_takeoff_splitter_sizes=lambda sizes: calls.append(("takeoff", sizes)),
            set_left_splitter_sizes=lambda sizes: calls.append(("left", sizes)),
        )
        coordinator._restore_takeoff_splitter_sizes_after_show([100, 200])
        coordinator._restore_left_splitter_sizes_after_show([30, 70])
        self.assertEqual(calls, [("takeoff", [100, 200]), ("left", [30, 70])])

    def test_reset_to_defaults_persists_default_workspace_and_reapplies_state(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        timer = _detached_support_FakeWorkspaceSaveTimer(active=True)
        persisted = WorkspaceState()
        persisted.dialog_sizes["cover_sheet"] = [760, 560]
        persisted.takeoff_workspace.left_splitter_sizes = [651, 242]
        model, repository = _detached_support__workspace_state_model(persisted)
        self.assertEqual(model.state.dialog_sizes, {"cover_sheet": [760, 560]})
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
        self.assertEqual(repository.load(), WorkspaceState())
        self.assertEqual(model.state, WorkspaceState())
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

    def test_untracking_mesh_window_leaves_dropdown_signal_connected(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        window = _detached_support_TrackableDetachedWindow()
        callback = lambda *_args: None
        key = WorkspaceStateCoordinator._DETACHED_MESH
        coordinator._tracked_detached_destroy_callbacks = {key: callback}
        window.installEventFilter(coordinator)
        coordinator._untrack_detached_window(key, window)
        self.assertEqual(window.installed_filters, [])
        self.assertEqual(window.dropdown_size_changed.disconnected, [])
        self.assertEqual(window.destroyed.disconnected, [callback])

    def test_untracking_deleted_window_still_releases_destroy_callback(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        window = _detached_support_TrackableDetachedWindow()
        callback = lambda *_args: None
        key = WorkspaceStateCoordinator._DETACHED_VIEW

        def removeEventFilter(_filter):
            raise RuntimeError("wrapped C++ object deleted")

        window.removeEventFilter = removeEventFilter
        coordinator._tracked_detached_destroy_callbacks = {key: callback}
        coordinator._untrack_detached_window(key, window)
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

    def test_late_dropdown_resize_after_cleanup_is_ignored(self):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        timer = _detached_support_FakeWorkspaceSaveTimer(active=False)
        coordinator._cleaned_up = True
        coordinator._save_timer = timer
        coordinator._state = None
        coordinator._shell = None
        coordinator._on_dropdown_size_changed()
        self.assertFalse(timer.started)

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


class WorkspaceStateDropdownMergeTests(unittest.TestCase):
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

    def test_popup_size_merge_drops_unknown_invalid_and_extra_values_without_mutation(
        self,
    ):
        coordinator = WorkspaceStateCoordinator.__new__(WorkspaceStateCoordinator)
        previous = {
            "main_page": [220, 330],
            "view_page": [700],
            "unknown_popup": [10, 10],
        }
        current = {
            "main_page": [0, 400],
            "main_area": [300, -1],
            "annotation_page": [640, 420, 99],
            "view_named_views": [710, 510],
            "unknown_popup": [900, 900],
        }
        merged = coordinator._merge_dropdown_popup_sizes(previous, current)
        self.assertEqual(
            merged,
            {
                "main_page": [220, 330],
                "annotation_page": [640, 420],
                "view_named_views": [710, 510],
            },
        )
        self.assertEqual(
            previous,
            {"main_page": [220, 330], "view_page": [700], "unknown_popup": [10, 10]},
        )
        self.assertIsNot(merged["main_page"], previous["main_page"])
        self.assertEqual(coordinator._merge_dropdown_popup_sizes(None, None), {})
