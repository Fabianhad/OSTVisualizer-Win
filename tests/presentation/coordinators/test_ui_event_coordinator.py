from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
)
from ost_visualizer.presentation.config import (
    COMPACT_SPACING,
    OPTIONS_DIALOG_TITLE,
    OPTIONS_GROUP_AUTO_ZOOM,
    OPTIONS_GROUP_CONFIRMATIONS,
    OPTIONS_GROUP_PREFERENCES,
    OPTIONS_GROUP_SNAP_ANGLE,
    OPTIONS_LABEL_RESET_ALL_SETTINGS,
    OPTIONS_TAB_EXPORT,
    OPTIONS_TAB_FONTS_COLORS,
    OPTIONS_TAB_MCP_SETUP,
    OPTIONS_TAB_OPTIONS,
    OPTIONS_TAB_TAKEOFF_TOOLBAR,
    OPTIONS_WINDOW_WIDTH,
    RELAXED_SPACING,
    TAB_INDEX_TAKEOFF,
)
from ost_visualizer.domain.entities.config import Config
from pathlib import Path
from tests.presentation.managers.deferred_persistence_support import (
    FakeIndexWidget,
    FakeProjectWriteService,
    FakeSqlWorkspaceService,
    RecordingDeferredPersistence,
    RecordingNativeMeshView,
    RecordingPlanView,
    _workspace_service,
)
from ost_visualizer.presentation.managers.deferred_persistence_manager import (
    DeferredPersistenceManager,
)
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from ost_visualizer.presentation.components.layers_sidebar import BidLayersSidebar
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_RECT,
    ANNOTATION_TYPE_TEXT,
)
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
    WriteReloadResult,
)
import logging
from tests.presentation.coordinators.ui_event_coordinator_support import (
    DeferredNavigationOperations,
    FakeAccess,
    FakeConstructedMeshWindow,
    FakeDeferredPersistence,
    FakeMainWindow,
    FakeMenuController,
    FakeMeshAccess,
    FakeMeshPlanSignaler,
    FakeMeshReceiver,
    FakeNav,
    FakePageSettingsBar,
    FakePlacement,
    FakeProjectData,
    FakeProjectView,
    FakeRefreshNav,
    FakeRefreshSnapshot,
    FakeRefreshUiState,
    FakeSidebar,
    FakeSignal,
    FakeSqlCollaboration,
    FakeTabWidget,
    FakeTakeoffSidebar,
    FakeToolbar,
    FakeUiState,
    FakeUndo,
    FakeUnloadMainWindow,
    FakeUnloadProjectData,
    FakeUnloadUiState,
    FakeUnloadViewer,
    FakeViewStack,
    FakeViewer,
    FakeVisualization,
    ImmediateNavigationOperations,
    NavigationStatusProjectData,
    NavigationStatusUiState,
    _CollaborationStatusPanel,
    configure_mesh_state,
    mesh_geometry,
    mesh_publication,
    navigation_status_coordinator,
    scene_identity,
)
from shiboken6 import delete
from PySide6 import QtWidgets
from ost_visualizer.presentation.services.bid_clipboard_service import (
    BidClipboardService,
)
from ost_visualizer.presentation.modes.cursor import (
    CURSOR_MODE_PLACE,
    CURSOR_MODE_SELECT,
)
from ost_visualizer.presentation.managers.ui_state_manager import UIStateManager
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
    _MeshScenePublication,
)
from ost_visualizer.presentation.coordinators.placement_coordinator import (
    PlacementCoordinator,
)
from ost_visualizer.presentation.coordinators.navigation_state_machine import (
    NavigationStateMachine,
    NavState,
)
from ost_visualizer.presentation.config import (
    TAB_INDEX_PROJECTS,
    TAB_INDEX_SUMMARY,
    TAB_INDEX_TAKEOFF,
)
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from ost_visualizer.application.services.project_write_service import WriteReloadResult
from ost_visualizer.application.interfaces.i_database_catalog import (
    DatabaseCatalogError,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.dtos.remote_projection_dtos import (
    RemoteProjectionBarrier,
)
from ost_visualizer.application.dtos.mesh_geometry_dto import (
    MeshGeometry,
    MeshSceneIdentity,
)
from ost_visualizer.application.dtos.conflict_resolution_dtos import (
    ConflictResolutionAction,
)
from ost_visualizer.application.dtos.collaboration_resource_catalog import (
    CollaborationResourceFamily,
    CollaborationResourceType,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    CollaborationStatus,
    EditLeaseHandle,
    EditLeaseLoss,
    EditLeaseResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceRef,
    SynchronizationState,
)
from unittest.mock import patch
import os
import unittest
from types import SimpleNamespace
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from PySide6 import QtCore, QtGui, QtWidgets
from ost_visualizer.application.dtos.condition_summary_dtos import (
    SUMMARY_GROUP_AREA,
    SUMMARY_GROUP_PAGE,
    SUMMARY_GROUP_TYPE,
    SUMMARY_MULTI_AREA_TOTAL_LABEL,
    SUMMARY_NO_PAGE_LABEL,
    SUMMARY_NODE_AREA_DETAIL,
    SUMMARY_NODE_CONDITION,
    SUMMARY_NODE_FOLDER,
    SUMMARY_NODE_GROUP,
    SUMMARY_NODE_MULTI_AREA_TOTAL,
    SUMMARY_NODE_ROOT,
    ConditionSummaryGrouping,
)
from ost_visualizer.application.use_cases.project.condition_summary_service import (
    ConditionSummaryService,
)
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.services.uom_service import CALC_COUNT, UOM_EACH
from ost_visualizer.presentation.components.condition_summary import ConditionSummaryTab
from ost_visualizer.presentation.coordinators.navigation_state_machine import NavState
from ost_visualizer.presentation.handlers.condition_action_handler import (
    ConditionActionHandler,
)
from ost_visualizer.presentation.utils.persistent_header import (
    PersistentHeaderController,
)
from PySide6 import QtCore, QtWidgets
from tests.helpers.workspace_state import make_workspace_state_model
from unittest.mock import Mock, patch
from ost_visualizer.presentation.dialogs.set_scale_dialog import (
    ScaleSettings,
    SetScaleDialog,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    EditLeaseHandle,
    EditLeaseResult,
    ResourceRef,
)
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyData,
    HierarchyFileEntry,
)
from tests.presentation.utils.dialog_lifecycle_support import (
    _app as _dialog_lifecycle_support__app,
)
from ost_visualizer.presentation.managers.ui_access_manager import (
    _DATABASE_EDIT_FEATURES,
    MAIN_PLAN_SURFACE_ID,
    Feature,
    UIAccessManager,
)
import uuid
from ost_visualizer.application.dtos.collaboration_dtos import (
    DatabaseMutationResult,
    EditLeaseHandle,
    MutationOutcomeStatus,
    PlanItemsPastePayload,
    ProjectWritePayload,
    QueuedMutationResult,
    ResourceRef,
)
from ost_visualizer.domain.entities.cover_sheet import JobStatus
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_NAMED_VIEW,
    BidAnnotation,
)
from ost_visualizer.presentation.config import (
    TAB_INDEX_TAKEOFF,
    VIEWER_SCALE_COMBO_WIDTH,
)
from tests.presentation.coordinators.hotlink_navigation_support import (
    FakeHotlinkPlanView as _detached_support_FakeHotlinkPlanView,
    FakeHotlinkSidebar as _detached_support_FakeHotlinkSidebar,
    FakeHotlinkTabWidget as _detached_support_FakeHotlinkTabWidget,
    FakeHotlinkViewer as _detached_support_FakeHotlinkViewer,
)
from unittest.mock import Mock
from unittest.mock import Mock, patch, MagicMock
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyPageInfo,
    HierarchyFolderInfo,
)
import tests.integration.pages.test_set_scale_apply as scale_fixture
import tests.integration.refresh.test_local_family_ownership as scope_fixture
import random
import traceback
from dataclasses import dataclass, field

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.mesh_geometry_dto import MeshSceneIdentity
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from PySide6.QtWidgets import QApplication
from tests.presentation.coordinators.ui_event_coordinator_support import (
    FakeMainWindow as CoordinatorFakeMainWindow,
)
from tests.presentation.coordinators.ui_event_coordinator_support import (
    FakeMeshAccess as CoordinatorFakeMeshAccess,
)
from tests.presentation.coordinators.ui_event_coordinator_support import (
    FakeMeshPlanSignaler as CoordinatorFakeMeshPlanSignaler,
)
from tests.presentation.coordinators.ui_event_coordinator_support import (
    FakeMeshReceiver as CoordinatorFakeMeshReceiver,
)
from tests.presentation.coordinators.ui_event_coordinator_support import (
    FakeNav as CoordinatorFakeNav,
)
from tests.presentation.coordinators.ui_event_coordinator_support import (
    FakePageSettingsBar as CoordinatorFakePageSettingsBar,
)
from tests.presentation.coordinators.ui_event_coordinator_support import (
    FakePlacement as CoordinatorFakePlacement,
)
from tests.presentation.coordinators.ui_event_coordinator_support import (
    FakeProjectData as CoordinatorFakeProjectData,
)
from tests.presentation.coordinators.ui_event_coordinator_support import (
    FakeSidebar as CoordinatorFakeSidebar,
)
from tests.presentation.coordinators.ui_event_coordinator_support import (
    FakeTakeoffSidebar as CoordinatorFakeTakeoffSidebar,
)
from tests.presentation.coordinators.ui_event_coordinator_support import (
    FakeToolbar as CoordinatorFakeToolbar,
)
from tests.presentation.coordinators.ui_event_coordinator_support import (
    FakeUiState as CoordinatorFakeUiState,
)
from tests.presentation.coordinators.ui_event_coordinator_support import (
    FakeViewer as CoordinatorFakeViewer,
)
from tests.presentation.coordinators.ui_event_coordinator_support import (
    FakeVisualization as CoordinatorFakeVisualization,
)
from tests.presentation.coordinators.ui_event_coordinator_support import (
    configure_mesh_state,
)

DEFAULT_CHAOS_SEEDS = (101, 202, 303, 404, 505)
DEFAULT_CHAOS_STEPS = 35


def _chaos_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    return int(raw)


def _configured_seeds() -> list[int]:
    explicit = os.environ.get("PRESENTATION_CHAOS_SEED")
    if explicit not in (None, ""):
        return [int(explicit)]
    count = _env_int("PRESENTATION_CHAOS_SEEDS", len(DEFAULT_CHAOS_SEEDS))
    return list(DEFAULT_CHAOS_SEEDS[: max(1, count)])


@dataclass
class ChaosActionResult:
    name: str
    detail: str = ""

    def describe(self) -> str:
        return self.name if not self.detail else f"{self.name}: {self.detail}"


class CoordinatorChaosPlanView:
    def __init__(self):
        self.reset_ctrl_held_calls = 0

    def reset_ctrl_held(self):
        self.reset_ctrl_held_calls += 1


class UIEventCoordinatorChaosHarness:
    def __init__(self, seed: int, test_case: unittest.TestCase):
        self.seed = seed
        self.test_case = test_case
        self.rng = random.Random(seed)
        self.history: list[ChaosActionResult] = []
        self.coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        self.coordinator.ui_state_manager = CoordinatorFakeUiState()
        self.active_bid_ref = BidRef("chaos.mdb", "bid-1")
        self.coordinator.project_data = CoordinatorFakeProjectData()
        self.coordinator.takeoff_sidebar = CoordinatorFakeTakeoffSidebar()
        self.coordinator._page_settings_bar = CoordinatorFakePageSettingsBar()
        self.coordinator._viewer = CoordinatorFakeViewer()
        self.coordinator._sidebar = CoordinatorFakeSidebar()
        self.coordinator._toolbar = CoordinatorFakeToolbar()
        self.coordinator.main_window = CoordinatorFakeMainWindow()
        self.coordinator._placement = CoordinatorFakePlacement()
        self.coordinator._is_cleaning_up = False
        self.coordinator._nav = CoordinatorFakeNav()
        self.coordinator.ui_access_manager = CoordinatorFakeMeshAccess()
        self.coordinator._plan_view_signaler = CoordinatorFakeMeshPlanSignaler()
        self.coordinator.plan_view = CoordinatorChaosPlanView()
        self.coordinator._pending_hotlink_page_uid = None
        self.coordinator._pending_hotlink_named_view = None
        self.coordinator._last_mesh_scene = None
        self.coordinator._sync_page_info_status = self._record_page_info_update
        self.page_info_updates = 0
        configure_mesh_state(
            self.coordinator,
            visualization=CoordinatorFakeVisualization(),
            opengl_viewer=CoordinatorFakeMeshReceiver(),
        )
        self.known_pages = {"page-1", "page-2"}

    def run_random_actions(self, steps: int) -> None:
        for index in range(steps):
            self._run_action(index, self.rng.choice(self._all_actions()))

    def run_sequence(self, names: list[str]) -> None:
        actions = {
            action.__name__.replace("action_", ""): action
            for action in self._all_actions()
        }
        for index, name in enumerate(names):
            self._run_action(index, actions[name])

    def _all_actions(self):
        return [
            self.action_takeoffs_changed_active_page,
            self.action_takeoffs_changed_other_page,
            self.action_annotations_changed_active_page,
            self.action_annotations_changed_no_page,
            self.action_clear_selected_pages,
            self.action_restore_selected_pages,
            self.action_switch_to_3d_view,
            self.action_switch_to_2d_view,
            self.action_native_scene_updated,
            self.action_toggle_detached_mesh,
        ]

    def _run_action(self, index: int, action) -> None:
        try:
            result = action()
            self.history.append(result)
            _chaos_app().processEvents()
            self._assert_invariants()
        except Exception as exc:
            self.test_case.fail(self._failure_message(index, action.__name__, exc))

    def _record_page_info_update(self):
        self.page_info_updates += 1

    def action_takeoffs_changed_active_page(self) -> ChaosActionResult:
        self.coordinator._on_takeoffs_changed(
            page_uid="page-1",
            takeoff_uids=["t-1"],
            condition_uids=["c-1"],
        )
        return ChaosActionResult("takeoffs_changed_active_page")

    def action_takeoffs_changed_other_page(self) -> ChaosActionResult:
        self.coordinator._on_takeoffs_changed(
            page_uid="page-2",
            takeoff_uids=["t-2"],
            condition_uids=["c-2"],
        )
        return ChaosActionResult("takeoffs_changed_other_page")

    def action_annotations_changed_active_page(self) -> ChaosActionResult:
        self.coordinator._on_annotations_changed(
            page_uid="page-1",
            annotation_uids=["ann-1"],
            annotation_types=[ANNOTATION_TYPE_TEXT],
        )
        return ChaosActionResult("annotations_changed_active_page")

    def action_annotations_changed_no_page(self) -> ChaosActionResult:
        self.coordinator._on_annotations_changed(
            page_uid="",
            annotation_uids=["ann-empty"],
            annotation_types=[ANNOTATION_TYPE_TEXT],
        )
        return ChaosActionResult("annotations_changed_no_page")

    def action_clear_selected_pages(self) -> ChaosActionResult:
        self.coordinator.project_data.selected_page_uids = []
        return ChaosActionResult("clear_selected_pages")

    def action_restore_selected_pages(self) -> ChaosActionResult:
        self.coordinator.project_data.selected_page_uids = ["page-1"]
        return ChaosActionResult("restore_selected_pages")

    def action_switch_to_3d_view(self) -> ChaosActionResult:
        self.coordinator._view_stack.setCurrentIndex(0)
        self.coordinator._on_view_stack_changed(0)
        return ChaosActionResult("switch_to_3d_view")

    def action_switch_to_2d_view(self) -> ChaosActionResult:
        self.coordinator._view_stack.setCurrentIndex(1)
        self.coordinator._on_view_stack_changed(1)
        return ChaosActionResult("switch_to_2d_view")

    def action_native_scene_updated(self) -> ChaosActionResult:
        with unittest.mock.patch.object(
            self.coordinator.ui_state_manager,
            "get_selected_bid_ref",
            return_value=self.active_bid_ref,
        ):
            self.coordinator._on_native_scene_updated(
                geometries=[],
                scene_identity=MeshSceneIdentity(
                    self.active_bid_ref,
                    tuple(self.coordinator.project_data.get_selected_page_uids()),
                    1,
                ),
                scene_failed=False,
            )
        return ChaosActionResult("native_scene_updated")

    def action_toggle_detached_mesh(self) -> ChaosActionResult:
        if self.coordinator._mesh_window is None:
            self.coordinator._mesh_window = CoordinatorFakeMeshReceiver(visible=True)
            state = "open"
        else:
            self.coordinator._mesh_window = None
            state = "closed"
        return ChaosActionResult("toggle_detached_mesh", state)

    def _assert_invariants(self) -> None:
        dirty_pages = set(self.coordinator._dirty_mesh_page_uids)
        unknown_dirty_pages = dirty_pages - self.known_pages
        if unknown_dirty_pages:
            raise AssertionError(
                f"dirty mesh pages are unknown: {sorted(unknown_dirty_pages)}"
            )
        selected_pages = set(self.coordinator.project_data.selected_page_uids)
        unknown_selected_pages = selected_pages - self.known_pages
        if unknown_selected_pages:
            raise AssertionError(
                f"selected mesh pages are unknown: {sorted(unknown_selected_pages)}"
            )
        invalid_plan_pages = [
            page_uid
            for page_uid in self.coordinator._viewer.plan_pages
            if page_uid not in self.known_pages and page_uid != "active"
        ]
        if invalid_plan_pages:
            raise AssertionError(
                f"viewer refreshed invalid plan pages: {invalid_plan_pages}"
            )
        if self.coordinator._view_stack.currentIndex() == 0:
            if self.coordinator._placement.is_active:
                raise AssertionError("placement stayed active after switching to 3D")
            if self.coordinator.ui_state_manager.place_condition_uid is not None:
                raise AssertionError("place condition stayed set after switching to 3D")
        for pages in self.coordinator.visualization_service.mesh_pages:
            unknown_pages = set(pages) - self.known_pages
            if unknown_pages:
                raise AssertionError(f"mesh refresh requested unknown pages: {pages}")
        if (
            not self.coordinator._mesh_scene_dirty
            and self.coordinator._dirty_mesh_page_uids
        ):
            raise AssertionError(
                "dirty mesh page set remained after mesh state was clean"
            )

    def _failure_message(self, index: int, action_name: str, exc: BaseException) -> str:
        return (
            "UI event coordinator chaos harness failure\n"
            f"Current state: {{'seed': {self.seed}, 'action_index': {index}, "
            f"'action': {action_name.replace('action_', '')!r}, "
            f"'view_index': {self.coordinator._view_stack.currentIndex()}, "
            f"'selected_pages': {self.coordinator.project_data.selected_page_uids}, "
            f"'plan_pages': {self.coordinator._viewer.plan_pages[-10:]}, "
            f"'mesh_pages': {self.coordinator.visualization_service.mesh_pages[-10:]}, "
            f"'mesh_dirty': {self.coordinator._mesh_scene_dirty}, "
            f"'dirty_pages': {sorted(self.coordinator._dirty_mesh_page_uids)}, "
            f"'pending_dirty_refresh': {self.coordinator._pending_dirty_mesh_refresh}}}\n"
            f"Recent actions: {[entry.describe() for entry in self.history[-15:]]}\n"
            f"Exception: {exc!r}\n"
            f"{traceback.format_exc()}"
        )


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _summary_nodes(node):
    result = [node]
    for child in node.children:
        result.extend(_summary_nodes(child))
    return result


def _condition_row_uids(node):
    return [
        child.condition_uid
        for child in _summary_nodes(node)
        if child.kind in (SUMMARY_NODE_CONDITION, SUMMARY_NODE_MULTI_AREA_TOTAL)
    ]


def _attach_summary_header(tab):
    controller = PersistentHeaderController(
        tab.tree,
        "condition_summary_test",
        tab.column_keys,
        make_workspace_state_model(),
        sorting=True,
        movable=True,
        default_sort_column="name",
    )
    tab.columns_about_to_change.connect(controller.begin_columns_update)
    tab.columns_changed.connect(controller.end_columns_update)
    return controller


class _FakeSummaryAccess:
    def __init__(self, allowed):
        self._allowed = set(allowed)

    def is_allowed(self, feature):
        return feature in self._allowed


class UiEventCoordinatorConditionBehaviorTests(unittest.TestCase):
    def _make_conditions(self, count: int, prefix: str = "c"):
        return {
            f"{prefix}{index}": Condition(
                uid=f"{prefix}{index}",
                name=f"Condition {index}",
                ref_no=index,
            )
            for index in range(1, count + 1)
        }

    def test_takeoff_owned_highlight_repairs_real_sidebar_projection(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions = self._make_conditions(2)
        sidebar.load_conditions(conditions, {}, "Project")

        class UiState:
            highlighted_condition_uids = set()

            def set_highlighted_conditions(self, uids):
                self.highlighted_condition_uids = set(uids)

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = UiState()
        coordinator.project_data = SimpleNamespace(
            get_all_takeoffs=lambda: [
                Takeoff(uid="t1", condition_uid="c1"),
                Takeoff(uid="t2", condition_uid="c2"),
            ]
        )
        coordinator.conditions_sidebar = sidebar
        coordinator.plan_view = None
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator._placement = SimpleNamespace(
            is_active=False,
            condition_uid=None,
            enter=lambda *_args: None,
        )
        coordinator._toolbar = SimpleNamespace(refresh=lambda: None)
        coordinator._tab_widget = SimpleNamespace(currentIndex=lambda: 1)
        coordinator._nav = SimpleNamespace(is_refreshing=False)
        coordinator._selected_takeoff_uids = ()
        coordinator._selection_projected_condition_uids = set()
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1", "t2"])
        self.assertEqual(set(sidebar.get_selected_condition_uids()), {"c1", "c2"})
        sidebar.tree.clearSelection()
        sidebar._sync_button_states()
        self.assertEqual(sidebar.get_selected_condition_uids(), [])
        self.assertEqual(
            coordinator.ui_state_manager.highlighted_condition_uids, {"c1", "c2"}
        )
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1", "t2"])
        self.assertEqual(set(sidebar.get_selected_condition_uids()), {"c1", "c2"})
        self.assertEqual(
            coordinator.ui_state_manager.highlighted_condition_uids, {"c1", "c2"}
        )

    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls._quit_on_last_window_closed = cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.setQuitOnLastWindowClosed(cls._quit_on_last_window_closed)

    def tearDown(self):
        self.app.processEvents()


class _UIEventCoordinatorTakeoffsChangedFixture(unittest.TestCase):
    def _make_page_selection_coordinator(self, *, bid_ref=None, current_state=None):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        nav = NavigationStateMachine()
        if current_state is not None:
            nav.transition_to(NavState.FILE_LOADED_NO_BID)
            if current_state in {
                NavState.BID_ACTIVE_NO_PAGES,
                NavState.BID_ACTIVE_PAGES_SELECTED,
            }:
                nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)
            if current_state == NavState.BID_ACTIVE_PAGES_SELECTED:
                nav.transition_to(NavState.BID_ACTIVE_PAGES_SELECTED)
        coordinator._nav = nav

        class UiState:
            def __init__(self):
                self.selected_page_uids = []
                self.selected_area_uid = ""
                self.set_page_selection_calls = []

            def get_selected_bid_ref(self):
                return bid_ref

            def set_page_selection(self, page_uids):
                self.selected_page_uids = list(page_uids)
                self.set_page_selection_calls.append(list(page_uids))

        class ProjectData:
            def __init__(self):
                self.select_calls = []

            def select_pages(self, page_uids):
                self.select_calls.append(list(page_uids))
                return [uid for uid in page_uids if uid == "page-1"]

        coordinator.ui_state_manager = UiState()
        coordinator.project_data = ProjectData()
        coordinator.ui_access_manager = type(
            "Access",
            (),
            {"is_allowed": lambda _self, _feature: False},
        )()
        coordinator._sidebar = type(
            "Sidebar",
            (),
            {"update_conditions_quantities": lambda _self: None},
        )()
        coordinator._update_export_menu_state = lambda: None
        coordinator._sync_page_info_status = lambda: None
        return coordinator

    def _make_3d_page_selection_coordinator(self):
        bid_ref = BidRef("active.mdb", "bid-1")
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._nav = NavigationStateMachine()
        coordinator._nav.transition_to(NavState.FILE_LOADED_NO_BID)
        coordinator._nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)

        class UiState:
            def __init__(self):
                self.selected_page_uids = []
                self.active_page_uid = "page-a"
                self.selected_area_uid = ""

            def get_selected_bid_ref(self):
                return bid_ref

            def set_page_selection(self, page_uids):
                self.selected_page_uids = list(page_uids)

        class ProjectData:
            def __init__(self):
                self.selected_page_uids = []

            def select_pages(self, page_uids):
                self.selected_page_uids = [
                    uid for uid in page_uids if uid in {"page-a", "page-b"}
                ]
                return list(self.selected_page_uids)

            def get_selected_page_uids(self):
                return list(self.selected_page_uids)

        coordinator.ui_state_manager = UiState()
        coordinator.project_data = ProjectData()
        coordinator.ui_access_manager = FakeMeshAccess()
        coordinator._sidebar = SimpleNamespace(
            update_conditions_quantities=lambda: None
        )
        coordinator._update_export_menu_state = lambda: None
        coordinator._sync_page_info_status = lambda: None
        coordinator._plan_view_signaler = FakeMeshPlanSignaler()
        embedded = FakeMeshReceiver()
        detached = FakeMeshReceiver()
        configure_mesh_state(
            coordinator,
            view_index=0,
            opengl_viewer=embedded,
            mesh_window=detached,
        )
        return coordinator, bid_ref, embedded, detached

    def _make_unload_coordinator(
        self, selected_file="active.mdb", current_file="active.mdb"
    ):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._plan_view_handler = None
        coordinator.project_operations = ImmediateNavigationOperations()
        coordinator._sql_collaboration = FakeSqlCollaboration()
        coordinator._status_panel = None
        coordinator.ui_state_manager = FakeUnloadUiState(selected_file)
        coordinator.project_data = FakeUnloadProjectData(current_file)
        coordinator.main_window = FakeUnloadMainWindow()
        coordinator._placement = FakePlacement()
        coordinator._undo_service = None
        coordinator.ui_access_manager = FakeAccess()
        coordinator._viewer = FakeUnloadViewer()
        coordinator.plan_view = None
        coordinator._sidebar = FakeSidebar()
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator.visualization_service = FakeVisualization()
        coordinator._tab_widget = FakeTabWidget(index=1)
        coordinator._toolbar = FakeToolbar()
        coordinator._bid_clipboard = None
        coordinator._pending_3d_takeoff_uids_by_bid = {}
        coordinator._nav = FakeNav()
        coordinator._bid_data_cache = {}
        coordinator._takeoff_workspace_bid_ref = None
        coordinator._pending_takeoff_page_uids = None
        coordinator._pending_takeoff_active_page_uid = None
        coordinator._pending_takeoff_selected_area_uid = ""
        coordinator._pending_takeoff_place_condition_uid = None
        coordinator._pending_takeoff_place_condition_uids = []
        coordinator._selected_takeoff_uids = ()
        coordinator._selection_projected_condition_uids = set()
        coordinator._page_settings_bar = None
        coordinator._mesh_scene_dirty = False
        coordinator._dirty_mesh_page_uids = set()
        coordinator._pending_dirty_mesh_refresh = False
        coordinator._clear_mesh_replay_buffer = lambda: None
        return coordinator


class UIEventCoordinatorTakeoffsChangedTests(_UIEventCoordinatorTakeoffsChangedFixture):
    """UIEventCoordinator: lifecycle and combined contracts."""

    def test_pending_3d_mutations_remain_scoped_across_database_switches(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        first_ref = BidRef("first.mdb", "bid-1")
        second_ref = BidRef("second.mdb", "bid-2")
        active_ref = [first_ref]
        coordinator.ui_state_manager = FakeUiState(first_ref)
        coordinator.ui_state_manager.get_selected_bid_ref = lambda: active_ref[0]
        embedded = FakeMeshReceiver()
        detached = FakeMeshReceiver()
        configure_mesh_state(
            coordinator,
            opengl_viewer=embedded,
            mesh_window=detached,
        )
        coordinator._on_pending_plan_mutations_changed(
            "first.mdb", ["shared-takeoff"], True, bid_uid=first_ref.bid_uid
        )
        self.assertEqual(embedded.pending_mutation_uids, {"shared-takeoff"})
        self.assertEqual(detached.pending_mutation_uids, {"shared-takeoff"})
        active_ref[0] = second_ref
        coordinator._begin_mesh_views_for_bid_load(second_ref)
        self.assertEqual(embedded.pending_mutation_uids, set())
        self.assertEqual(detached.pending_mutation_uids, set())
        coordinator._on_pending_plan_mutations_changed(
            "second.mdb", ["shared-takeoff"], True, bid_uid=second_ref.bid_uid
        )
        coordinator._on_pending_plan_mutations_changed(
            "first.mdb", ["shared-takeoff"], False, bid_uid=first_ref.bid_uid
        )
        self.assertEqual(embedded.pending_mutation_uids, {"shared-takeoff"})
        self.assertEqual(detached.pending_mutation_uids, {"shared-takeoff"})
        active_ref[0] = first_ref
        coordinator._begin_mesh_views_for_bid_load(first_ref)
        self.assertEqual(embedded.pending_mutation_uids, set())
        self.assertEqual(detached.pending_mutation_uids, set())

    def test_rotate_takeoff_actions_dispatch_exact_left_and_right_quarter_turns(self):
        rotations = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.plan_view = SimpleNamespace(
            has_selected_takeoffs=True,
            rotate_selected_takeoffs=lambda degrees: rotations.append(degrees),
        )
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda feature: feature == Feature.EDIT_PLAN_ITEMS
        )
        coordinator.rotate_selected_takeoffs_left()
        coordinator.rotate_selected_takeoffs_right()
        self.assertEqual(rotations, [-90.0, 90.0])

    def test_condition_refresh_updates_sidebar_and_active_plan(self):
        calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._sidebar = SimpleNamespace(
            refresh_conditions_from_memory=lambda: calls.append("sidebar")
        )
        coordinator._viewer = SimpleNamespace(
            update_plan_view_for_active=lambda: calls.append("plan")
        )
        coordinator.refresh_conditions_ui()
        self.assertEqual(calls, ["sidebar", "plan"])

    def test_native_page_visibility_rebuilds_the_canonical_selected_page_texture(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        embedded = FakeMeshReceiver()
        detached = FakeMeshReceiver()
        coordinator.opengl_viewer = embedded
        coordinator._mesh_window = detached
        coordinator.ui_state_manager = SimpleNamespace(active_page_uid="unchecked-page")
        coordinator.project_data = SimpleNamespace(
            get_page=lambda _uid: SimpleNamespace(layer_visible=False)
        )
        coordinator._update_native_page_textures()
        self.assertEqual(embedded.plan_texture_updates, 1)
        self.assertEqual(detached.plan_texture_updates, 1)

    def test_license_event_keyword_contract_updates_ui(self):
        calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._viewer = SimpleNamespace(
            update_license_plan_state=lambda: calls.append("plan")
        )
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: False
        )
        coordinator._clear_mesh_views_for_scene_update = lambda: calls.append("clear")
        coordinator._toolbar = SimpleNamespace(refresh=lambda: calls.append("toolbar"))
        coordinator.ensure_select_mode = lambda: calls.append("select")
        event_bus = EventBus()
        event_bus.subscribe(
            AppEvents.LICENSE_STATUS_CHANGED,
            coordinator._on_license_status_changed,
        )
        event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=True)
        self.assertEqual(calls, ["plan", "clear", "select"])

    def test_empty_access_hierarchy_still_delegates_monitoring_to_database_owner(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._bid_data_cache = {}
        coordinator.visualization_service = FakeVisualization()
        coordinator._sync_monitoring_state()
        self.assertEqual(coordinator.visualization_service.monitoring_started, 1)
        self.assertEqual(coordinator.visualization_service.monitoring_stopped, 0)

    def test_stale_sql_failure_does_not_replace_active_access_selection(self):
        panel = _CollaborationStatusPanel()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._pending_takeoff_page_uids = None
        coordinator.ui_state_manager = SimpleNamespace(
            selected_file_path="C:/projects/active.mdb"
        )
        coordinator._status_panel = panel
        coordinator._plan_view_handler = None
        cancelled = []
        coordinator._deferred_persistence = SimpleNamespace(
            cancel_for_file=cancelled.append
        )
        coordinator._placement = SimpleNamespace(
            force_exit=lambda: self.fail(
                "an inactive database failure must not exit active placement"
            )
        )
        coordinator._on_collaboration_state_changed(
            database_id="sql-database-id",
            state=SynchronizationState.DISCONNECTED.value,
            message="server unavailable",
        )
        self.assertEqual(
            coordinator.ui_state_manager.selected_file_path,
            "C:/projects/active.mdb",
        )
        self.assertEqual(panel.states, [])
        self.assertEqual(cancelled, ["sql-database-id"])

    def test_selected_sql_failure_projects_disconnected_state(self):
        panel = _CollaborationStatusPanel()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._pending_takeoff_page_uids = None
        coordinator.ui_state_manager = SimpleNamespace(
            selected_file_path="sql-database-id"
        )
        coordinator._status_panel = panel
        hidden_previews = []
        cancelled = []
        placement_exits = []
        coordinator._deferred_persistence = SimpleNamespace(
            cancel_for_file=cancelled.append
        )
        coordinator._placement = SimpleNamespace(
            force_exit=lambda: placement_exits.append(True)
        )
        coordinator._plan_view_handler = SimpleNamespace(
            hide_pending_takeoff_placement_previews=lambda: hidden_previews.append(True)
        )
        coordinator._on_collaboration_state_changed(
            database_id="sql-database-id",
            state=SynchronizationState.DISCONNECTED.value,
            message="server unavailable",
        )
        self.assertEqual(
            panel.states,
            [(SynchronizationState.DISCONNECTED.value, "server unavailable")],
        )
        self.assertEqual(hidden_previews, [True])
        self.assertEqual(cancelled, ["sql-database-id"])
        self.assertEqual(placement_exits, [True])

    def test_selected_sql_mutation_projects_pending_count(self):
        panel = _CollaborationStatusPanel()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(
            selected_file_path="sql-database-id"
        )
        coordinator._status_panel = panel
        coordinator._sql_collaboration = SimpleNamespace(
            status=lambda database_id: CollaborationStatus(
                database_id,
                SynchronizationState.HEALTHY,
                "Connected",
            )
        )
        coordinator._on_collaboration_mutation_state_changed(
            database_id="sql-database-id",
            operation_id="operation-id",
            mutation_type="plan_items_delete",
            state="uncertain",
            message="Commit status is unknown.",
            pending_count=1,
        )
        self.assertEqual(
            panel.mutation_states,
            [("uncertain", 1, "Commit status is unknown.")],
        )
        self.assertEqual(
            panel.states,
            [(SynchronizationState.HEALTHY.value, "Connected")],
        )

    def test_sql_rename_page_navigation_transfers_all_page_ownership(self):
        requested = []
        released = []
        queued = []
        completions = []
        bid_ref = BidRef("sql-database", "7")
        pages = {
            "page-1": SimpleNamespace(uid="page-1", name="First"),
            "page-2": SimpleNamespace(uid="page-2", name="Second"),
        }

        class SqlCollaboration:
            @staticmethod
            def request_local_edit(
                database_id,
                resources,
                callback,
                *,
                dependency_resources=(),
                operation_id="",
                owning_surface="desktop",
            ):
                handle = EditLeaseHandle(
                    database_id=database_id,
                    draft_id=f"draft-{len(requested) + 1}",
                    runtime_generation=1,
                    operation_id=operation_id,
                    owning_surface=owning_surface,
                    resources=resources,
                    dependency_resources=dependency_resources,
                )
                requested.append(handle)
                callback(EditLeaseResult(True, handle=handle))

            @staticmethod
            def end_edit_lease(handle):
                released.append(handle)

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return True

            @staticmethod
            def queue_page_settings(
                database_id,
                bid_uid,
                setting_kind,
                updates,
                callback,
                *,
                edit_lease_handle,
            ):
                queued.append(
                    (
                        database_id,
                        bid_uid,
                        setting_kind,
                        updates,
                        edit_lease_handle,
                    )
                )
                callback(
                    QueuedMutationResult(
                        database_id=database_id,
                        runtime_generation=1,
                        operation_id="ca798819-bd86-476e-a79b-63e69f503eca",
                        outcome_status=MutationOutcomeStatus.COMMITTED,
                        authoritative_result=AuthoritativeMutationResult(
                            affected_page_uids=("page-2",),
                            affected_families=("pages",),
                        ),
                    )
                )
                return 1

        class FakeDialog:
            def __init__(
                self,
                _icon_provider,
                _parent,
                dialog_pages,
                current_page_uid,
                save_fn,
                *,
                save_async_fn,
            ):
                self.pages = dialog_pages
                self.current_page_uid = current_page_uid
                self.save_fn = save_fn
                self.save_async_fn = save_async_fn

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

            def reject(self):
                pass

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.main_window = object()
        coordinator.event_bus = EventBus()
        coordinator._icon_provider = object()
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-1",
            selected_file_path=bid_ref.file_path,
            get_selected_bid_ref=lambda: bid_ref,
        )
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        hierarchy_entry = HierarchyFileEntry(file_path=bid_ref.file_path)
        coordinator.project_data = SimpleNamespace(
            get_page=lambda uid: pages.get(uid),
            get_hierarchy=lambda: HierarchyData(loaded_files=[hierarchy_entry]),
        )
        coordinator.takeoff_sidebar = SimpleNamespace(
            get_page_order=lambda: ["page-1", "page-2"]
        )
        coordinator._project_write_service = WriteService()
        coordinator._sql_collaboration = SqlCollaboration()
        coordinator._flush_deferred_for_file = lambda _database_id: True
        from ost_visualizer.presentation.coordinators import ui_event_coordinator

        def execute(dialog, _event_bus):
            self.assertEqual([page.uid for page in dialog.pages], ["page-1", "page-2"])
            self.assertTrue(
                dialog.save_async_fn("page-2", "Renamed", completions.append)
            )

        with (
            patch.object(ui_event_coordinator, "RenamePageDialog", FakeDialog),
            patch.object(
                ui_event_coordinator, "exec_with_ost_blocking", side_effect=execute
            ),
        ):
            coordinator.open_rename_page_dialog()
        self.assertEqual(len(requested), 2)
        self.assertEqual(
            {resource.resource_id for resource in requested[0].resources},
            {"page-1", "page-2"},
        )
        self.assertIs(queued[0][4], requested[0])
        self.assertEqual(queued[0][2:4], ("name", [["page-2", "Renamed"]]))
        self.assertEqual(completions, [True])
        self.assertEqual(released, [requested[1]])

    def test_inactive_database_reconciliation_does_not_replace_active_project_state(
        self,
    ):
        reloads = []
        cancelled = []
        resumed = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.project_data = type(
            "ProjectData",
            (),
            {"get_current_file_path": lambda _self: "active-database"},
        )()
        coordinator._deferred_persistence = type(
            "Persistence",
            (),
            {
                "cancel_for_file": lambda _self, database_id: cancelled.append(
                    database_id
                )
            },
        )()
        coordinator.project_operations = type(
            "Operations",
            (),
            {
                "reload_database": lambda _self, database_id: (
                    reloads.append(database_id) or True
                )
            },
        )()
        coordinator.event_bus = type(
            "EventBus", (), {"publish": lambda _self, *_args, **_kwargs: None}
        )()
        coordinator._sql_collaboration = type(
            "Collaboration",
            (),
            {
                "resume_controlled_recovery": lambda _self, database_id: (
                    resumed.append(database_id) or True
                )
            },
        )()
        coordinator.main_window = object()
        coordinator._on_full_reconciliation_required("inactive-database", "gap")
        self.assertEqual(cancelled, ["inactive-database"])
        self.assertEqual(resumed, ["inactive-database"])
        self.assertEqual(reloads, [])

    def test_active_database_reconciliation_never_reloads_sql_on_the_qt_thread(self):
        cancelled = []
        resumed = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.project_data = type(
            "ProjectData",
            (),
            {"get_current_file_path": lambda _self: "database"},
        )()
        coordinator._deferred_persistence = type(
            "Persistence",
            (),
            {
                "cancel_for_file": lambda _self, database_id: cancelled.append(
                    database_id
                )
            },
        )()
        coordinator.project_operations = type(
            "Operations",
            (),
            {
                "reload_database": lambda _self, _database_id: self.fail(
                    "SQL recovery must remain on the collaboration worker"
                )
            },
        )()
        coordinator._sql_collaboration = type(
            "Collaboration",
            (),
            {
                "resume_controlled_recovery": lambda _self, database_id: (
                    resumed.append(database_id) or True
                )
            },
        )()
        coordinator.event_bus = type(
            "EventBus",
            (),
            {
                "publish": lambda _self, *_args, **_kwargs: self.fail(
                    "Recovery must not publish the normal reload event"
                )
            },
        )()
        coordinator.main_window = object()
        coordinator._on_full_reconciliation_required("database", "gap")
        self.assertEqual(cancelled, ["database"])
        self.assertEqual(resumed, ["database"])

    def test_plan_conflict_restores_select_mode_before_modal_dialog(self):
        sequence = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._sql_collaboration = type(
            "Collaboration",
            (),
            {
                "enter_resource_conflict": lambda _self, *_args: sequence.append(
                    "conflict"
                )
            },
        )()
        coordinator._icon_provider = object()
        coordinator.main_window = object()
        coordinator.event_bus = EventBus()
        coordinator.project_data = type(
            "ProjectData",
            (),
            {"get_current_file_path": lambda _self: "database"},
        )()
        coordinator._placement = SimpleNamespace(
            force_exit=lambda: sequence.append("placement-exit")
        )
        coordinator._set_plan_select_mode = lambda: sequence.append("select")
        coordinator._toolbar = SimpleNamespace(
            refresh=lambda: sequence.append("toolbar")
        )
        coordinator._plan_view_handler = SimpleNamespace(
            prepare_for_authoritative_refresh=lambda: sequence.append("pointer")
        )
        coordinator.plan_view = None

        class Dialog:
            @staticmethod
            def selected_action():
                return ConflictResolutionAction.CANCEL_READ_ONLY

            @staticmethod
            def deleteLater():
                sequence.append("delete")

        dialog = Dialog()

        def execute(_dialog, _event_bus):
            self.assertEqual(
                sequence,
                ["conflict", "placement-exit", "select", "toolbar", "pointer"],
            )
            sequence.append("dialog")

        with (
            patch(
                "ost_visualizer.presentation.coordinators.ui_event_coordinator.SynchronizationConflictDialog",
                return_value=dialog,
            ),
            patch(
                "ost_visualizer.presentation.coordinators.ui_event_coordinator.exec_with_ost_blocking",
                side_effect=execute,
            ),
        ):
            coordinator._on_synchronization_conflict(
                database_id="database",
                resource_type="takeoff",
                resource_id="t1",
                bid_uid="8",
                message="A takeoff changed or was deleted before this operation started.",
                blocks_database=False,
            )
        self.assertEqual(
            sequence,
            [
                "conflict",
                "placement-exit",
                "select",
                "toolbar",
                "pointer",
                "dialog",
                "delete",
            ],
        )

    def test_conflict_dialog_return_stops_after_main_window_is_destroyed(self):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        window = QtWidgets.QWidget()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._sql_collaboration = SimpleNamespace(
            enter_resource_conflict=lambda *_args: None,
            discard_local_draft=lambda *_args: self.fail(
                "destroyed conflict dialog must not discard a draft"
            ),
        )
        coordinator._icon_provider = object()
        coordinator.main_window = window
        coordinator.event_bus = EventBus()
        coordinator._prepare_for_modal_mutation_error = lambda _database_id: None
        coordinator._on_full_reconciliation_required = lambda *_args: self.fail(
            "destroyed conflict dialog must not start reconciliation"
        )

        class DestroyingConflictDialog(QtWidgets.QDialog):
            def __init__(self, _icon_provider, _message, _actions, parent=None):
                super().__init__(parent)

            def selected_action(self):
                raise AssertionError("destroyed conflict dialog must not be read")

            def set_interactive(self, _enabled):
                pass

        def destroy_window(dialog, _event_bus):
            delete(window)
            return QtWidgets.QDialog.DialogCode.Rejected

        with (
            patch(
                "ost_visualizer.presentation.coordinators.ui_event_coordinator."
                "SynchronizationConflictDialog",
                DestroyingConflictDialog,
            ),
            patch(
                "ost_visualizer.presentation.coordinators.ui_event_coordinator."
                "exec_with_ost_blocking",
                side_effect=destroy_window,
            ),
        ):
            coordinator._on_synchronization_conflict(
                database_id="database",
                resource_type="takeoff",
                resource_id="t1",
                bid_uid="8",
                message="Conflict",
                blocks_database=False,
            )
        app.processEvents()

    def test_edit_lease_loss_is_routed_only_to_its_exact_plan_owner(self):
        losses = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._plan_view_handler = SimpleNamespace(
            on_edit_lease_lost=losses.append
        )
        loss = EditLeaseLoss(
            database_id="inactive-database",
            draft_id="draft",
            runtime_generation=1,
            operation_id="edit-condition",
            owning_surface="detached-view",
            resources=(ResourceRef("condition", "42", 8),),
            reason="trust-lost",
        )
        coordinator._on_edit_lease_lost(loss)
        self.assertEqual(losses, [loss])

    def test_canonical_mesh_refresh_boundary_rejects_unlicensed_requests(self):
        coordinator, _bid_ref, embedded, detached = (
            self._make_3d_page_selection_coordinator()
        )
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: False
        )
        coordinator._request_or_defer_mesh_refresh(["page-a"])
        self.assertEqual(coordinator.visualization_service.mesh_pages, [])
        self.assertEqual(coordinator.visualization_service.cancelled_mesh_refreshes, 1)
        self.assertEqual(embedded.clear_calls, 1)
        self.assertEqual(detached.clear_calls, 1)

    def test_master_condition_type_save_warns_when_refresh_fails(self):
        warnings = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = object()
        coordinator.ui_access_manager = type(
            "Access",
            (),
            {"is_allowed": lambda _self, feature: feature == Feature.EDIT_MASTER_DATA},
        )()
        coordinator._project_write_service = type(
            "WriteService",
            (),
            {
                "save_condition_types_result": lambda _self, _path, _changes: (
                    WriteReloadResult(
                        {"new_condition_type": "type-new"},
                        write_success=True,
                        reload_success=False,
                    )
                )
            },
        )()
        from ost_visualizer.presentation.coordinators import ui_event_coordinator

        old_warning = ui_event_coordinator.show_warning
        ui_event_coordinator.show_warning = lambda *args: warnings.append(args)
        try:
            result = coordinator._save_master_condition_types(
                "db.mdb",
                {"new": [{"uid": "new_condition_type", "name": "Concrete"}]},
            )
        finally:
            ui_event_coordinator.show_warning = old_warning
        self.assertEqual(result, {"new_condition_type": "type-new"})
        self.assertEqual(len(warnings), 1)
        self.assertIn("could not be refreshed", warnings[0][2])

    def test_multi_page_annotation_event_projects_active_page_once(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = FakeUiState()
        coordinator.project_data = FakeProjectData()
        coordinator._viewer = FakeViewer()
        coordinator._sidebar = FakeSidebar()
        coordinator._toolbar = FakeToolbar()
        coordinator.main_window = FakeMainWindow()
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        coordinator._on_annotations_changed(
            page_uids=["page-2", "page-1", "page-2"],
            annotation_uids=["ann-1"],
            annotation_types=[ANNOTATION_TYPE_TEXT],
        )
        self.assertEqual(coordinator._viewer.plan_pages, ["page-1"])
        self.assertEqual(coordinator._viewer.changed_annotation_uids, [["ann-1"]])
        self.assertEqual(coordinator.main_window.menu_controller.updates, 1)

    def test_deferred_page_projection_completion_recovers_controls(self):
        bid_ref = BidRef("sql-db", "bid-1")
        ui_state = SimpleNamespace(
            active_page_uid="page-b",
            get_selected_bid_ref=lambda: bid_ref,
        )
        plan_view = SimpleNamespace(
            current_page_uid="page-a",
            has_active_remote_projection_blocker=lambda: False,
        )

        class DelayedViewer:
            def __init__(self):
                self.completion = None

            def request_remote_plan_update(self, *, completion, **_kwargs):
                self.completion = completion
                return True

        viewer = DelayedViewer()
        toolbar_states = []
        barrier_results = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = ui_state
        coordinator.plan_view = plan_view
        coordinator._viewer = viewer
        coordinator._is_cleaning_up = False
        coordinator.project_data = SimpleNamespace(
            get_selected_page_uids=lambda: ["page-b"]
        )
        coordinator._request_or_defer_mesh_refresh = lambda _pages: None
        coordinator._apply_pending_hotlink_named_view_focus = lambda **_kwargs: False
        coordinator._update_export_menu_state = lambda: toolbar_states.append(
            plan_view.current_page_uid == ui_state.active_page_uid
        )
        barrier = RemoteProjectionBarrier(
            database_id=bid_ref.file_path,
            runtime_generation=3,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=barrier_results.append,
        )
        coordinator._update_export_menu_state()
        coordinator._on_remote_plan_projection_requested(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            runtime_generation=3,
            families=(CollaborationResourceFamily.PAGES.value,),
            condition_uids=(),
            condition_changed_fields=None,
            condition_change_operations=(),
            areas_changed=False,
            resource_uids_by_family={},
            affected_page_uids_by_family={
                CollaborationResourceFamily.PAGES.value: ("page-b",)
            },
            barrier=barrier,
        )
        barrier.seal()
        self.assertEqual(toolbar_states, [False])
        self.assertIsNotNone(viewer.completion)
        self.assertEqual(barrier_results, [])
        plan_view.current_page_uid = "page-b"
        viewer.completion(True)
        self.assertEqual(toolbar_states, [False, True])
        self.assertEqual(barrier_results, [True])

    def test_remote_annotation_projection_skips_unaffected_main_page(self):
        bid_ref = BidRef("sql-db", "bid-1")
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-1",
            get_selected_bid_ref=lambda: bid_ref,
        )
        coordinator.plan_view = object()
        coordinator._viewer = FakeViewer()
        coordinator._is_cleaning_up = False
        completed = []
        barrier = RemoteProjectionBarrier(
            database_id=bid_ref.file_path,
            runtime_generation=3,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=completed.append,
        )
        coordinator._on_remote_plan_projection_requested(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            runtime_generation=3,
            families=(CollaborationResourceFamily.ANNOTATIONS.value,),
            condition_uids=(),
            condition_changed_fields=None,
            condition_change_operations=(),
            areas_changed=False,
            resource_uids_by_family={
                CollaborationResourceFamily.ANNOTATIONS.value: ("text/annotation-1",)
            },
            affected_page_uids_by_family={
                CollaborationResourceFamily.ANNOTATIONS.value: ("page-2",)
            },
            barrier=barrier,
        )
        barrier.seal()
        self.assertEqual(coordinator._viewer.remote_requests, [])
        self.assertEqual(completed, [True])

    def test_secondary_layer_hide_suspends_and_restores_multi_condition_tool(self):
        bid_ref = BidRef("active.mdb", "bid-1")
        bid_owner = object()
        conditions = {
            "primary": Condition(
                uid="primary",
                layer_uid="layer-1",
                layer_visible=True,
                condition_type=Condition.TYPE_AREA,
            ),
            "secondary": Condition(
                uid="secondary",
                layer_uid="layer-2",
                layer_visible=True,
                condition_type=Condition.TYPE_AREA,
            ),
        }
        ui_state = SimpleNamespace(
            active_page_uid="page-1",
            place_condition_uid="primary",
            place_condition_uids=["primary", "secondary"],
            state=SimpleNamespace(grayscale_enabled=False),
            get_selected_bid_ref=lambda: bid_ref,
        )

        class PlanView:
            cursor_mode = CURSOR_MODE_PLACE
            place_condition_uid = "primary"
            current_page_uid = "page-1"
            annotation_place_type = None

            def __init__(self):
                self.cursor_modes = []
                self.tool_revision = 0

            def set_cursor_mode(self, mode):
                if self.cursor_mode != mode:
                    self.tool_revision += 1
                self.cursor_mode = mode
                self.cursor_modes.append(mode)
                if mode == CURSOR_MODE_SELECT:
                    self.place_condition_uid = None
                    ui_state.place_condition_uid = None
                    ui_state.place_condition_uids = []

            @staticmethod
            def reset_ctrl_held():
                pass

            @staticmethod
            def apply_layer_visibility(_layer_uid, _show, _conditions):
                return True

        class Placement:
            def __init__(self, plan_view):
                self.plan_view = plan_view
                self.enter_calls = []

            def enter(self, condition_uid, condition_uids):
                self.enter_calls.append((condition_uid, list(condition_uids)))
                ui_state.place_condition_uid = condition_uid
                ui_state.place_condition_uids = list(condition_uids)
                self.plan_view.place_condition_uid = condition_uid
                self.plan_view.cursor_mode = CURSOR_MODE_PLACE
                return True

        layers = {
            "layer-1": SimpleNamespace(uid="layer-1", show=True),
            "layer-2": SimpleNamespace(uid="layer-2", show=True),
        }

        def update_layer_visibility(layer_uid, show):
            layers[layer_uid].show = show
            for condition in conditions.values():
                if condition.layer_uid == layer_uid:
                    condition.layer_visible = show
            return []

        plan_view = PlanView()
        placement = Placement(plan_view)
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.plan_view = plan_view
        coordinator.ui_state_manager = ui_state
        access = SimpleNamespace(place_allowed=True)
        access.is_allowed = lambda feature: bool(
            access.place_allowed and feature == Feature.PLACE_PLAN_ITEMS
        )
        coordinator.ui_access_manager = access
        coordinator.project_data = SimpleNamespace(
            get_bid=lambda ref: bid_owner if ref == bid_ref else None,
            get_bid_conditions=lambda: conditions,
            get_bid_layer_snapshot=lambda: list(layers.values()),
            is_image_layer_uid=lambda _uid: False,
            update_layer_visibility=update_layer_visibility,
            get_selected_page_uids=lambda: ["page-1"],
        )
        coordinator._placement = placement
        coordinator._suspended_layer_tool = None
        coordinator._toolbar = SimpleNamespace(set_select_checked=lambda: None)
        coordinator._sidebar = SimpleNamespace(bid_layers_sidebar=None)
        coordinator.conditions_sidebar = None
        coordinator.condition_summary_tab = None
        coordinator.event_bus = SimpleNamespace(publish=lambda *_args, **_kwargs: None)
        coordinator._request_or_defer_mesh_refresh = lambda _pages: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._is_takeoff_2d_view_active = lambda: True
        self.assertTrue(
            coordinator._project_layer_visibility_if_current(
                bid_ref, bid_owner, "layer-2", False
            )
        )
        self.assertEqual(plan_view.cursor_mode, CURSOR_MODE_SELECT)
        self.assertEqual(placement.enter_calls, [])
        self.assertTrue(
            coordinator._project_layer_visibility_if_current(
                bid_ref, bid_owner, "layer-2", True
            )
        )
        self.assertEqual(
            placement.enter_calls,
            [("primary", ["primary", "secondary"])],
        )
        self.assertEqual(plan_view.cursor_mode, CURSOR_MODE_PLACE)
        # Replacing a participating Condition with the same UID while the
        # Layer is hidden invalidates the exact suspended placement owners.
        self.assertTrue(
            coordinator._project_layer_visibility_if_current(
                bid_ref, bid_owner, "layer-2", False
            )
        )
        conditions["secondary"] = Condition(
            uid="secondary",
            layer_uid="layer-2",
            layer_visible=False,
            condition_type=Condition.TYPE_AREA,
        )
        self.assertTrue(
            coordinator._project_layer_visibility_if_current(
                bid_ref, bid_owner, "layer-2", True
            )
        )
        self.assertEqual(
            placement.enter_calls,
            [("primary", ["primary", "secondary"])],
        )
        self.assertEqual(plan_view.cursor_mode, CURSOR_MODE_SELECT)
        # Explicitly restarting placement creates a new owner snapshot, but a
        # later access loss still prevents automatic restoration.
        placement.enter("primary", ["primary", "secondary"])
        self.assertTrue(
            coordinator._project_layer_visibility_if_current(
                bid_ref, bid_owner, "layer-2", False
            )
        )
        access.place_allowed = False
        self.assertTrue(
            coordinator._project_layer_visibility_if_current(
                bid_ref, bid_owner, "layer-2", True
            )
        )
        self.assertEqual(
            placement.enter_calls,
            [
                ("primary", ["primary", "secondary"]),
                ("primary", ["primary", "secondary"]),
            ],
        )
        self.assertEqual(plan_view.cursor_mode, CURSOR_MODE_SELECT)
        # A newer explicit tool choice supersedes the suspended Takeoff intent,
        # even if the user returns to Select before the Layer is shown again.
        access.place_allowed = True
        placement.enter("primary", ["primary", "secondary"])
        self.assertTrue(
            coordinator._project_layer_visibility_if_current(
                bid_ref, bid_owner, "layer-2", False
            )
        )
        plan_view.set_cursor_mode("pan")
        plan_view.set_cursor_mode(CURSOR_MODE_SELECT)
        self.assertTrue(
            coordinator._project_layer_visibility_if_current(
                bid_ref, bid_owner, "layer-2", True
            )
        )
        self.assertEqual(
            placement.enter_calls,
            [
                ("primary", ["primary", "secondary"]),
                ("primary", ["primary", "secondary"]),
                ("primary", ["primary", "secondary"]),
            ],
        )
        self.assertEqual(plan_view.cursor_mode, CURSOR_MODE_SELECT)

    def test_remote_projection_request_failure_releases_registered_surface(self):
        database_id = "sql-db"
        bid_uid = "bid-1"

        class SelectedUiState(FakeUiState):
            def get_selected_bid_ref(self):
                return BidRef(database_id, bid_uid)

        class RaisingViewer:
            def request_remote_plan_update(
                self,
                *,
                database_id,
                runtime_generation,
                bid_uid,
                resource_uids_by_family,
                barrier,
                completion,
            ):
                del (
                    database_id,
                    runtime_generation,
                    bid_uid,
                    resource_uids_by_family,
                    barrier,
                    completion,
                )
                raise RuntimeError("snapshot failed")

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SelectedUiState()
        coordinator.project_data = SimpleNamespace(
            get_selected_page_uids=lambda: ["page-1"]
        )
        mesh_refreshes = []
        coordinator._request_or_defer_mesh_refresh = (
            lambda pages: mesh_refreshes.append(list(pages))
        )
        coordinator._viewer = RaisingViewer()
        coordinator.plan_view = object()
        coordinator._is_cleaning_up = False
        completed = []
        barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=3,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=completed.append,
        )
        with self.assertRaisesRegex(RuntimeError, "snapshot failed"):
            coordinator._on_remote_plan_projection_requested(
                database_id=database_id,
                bid_uid=bid_uid,
                runtime_generation=3,
                families=(CollaborationResourceFamily.TAKEOFFS.value,),
                condition_uids=(),
                condition_changed_fields=None,
                condition_change_operations=(),
                areas_changed=False,
                resource_uids_by_family={
                    CollaborationResourceFamily.TAKEOFFS.value: ("takeoff-1",)
                },
                barrier=barrier,
            )
        barrier.seal()
        self.assertEqual(mesh_refreshes, [["page-1"]])
        self.assertEqual(completed, [False])

    def test_annotations_changed_passes_metadata_without_quantity_refresh(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = FakeUiState()
        coordinator.project_data = FakeProjectData()
        coordinator._viewer = FakeViewer()
        coordinator._sidebar = FakeSidebar()
        coordinator._toolbar = FakeToolbar()
        coordinator.main_window = FakeMainWindow()
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        coordinator._on_annotations_changed(
            page_uid="page-1",
            annotation_uids=["ann-1"],
            annotation_types=[ANNOTATION_TYPE_TEXT],
        )
        self.assertEqual(coordinator._viewer.plan_pages, ["page-1"])
        self.assertEqual(coordinator._viewer.changed_takeoff_uids, [None])
        self.assertEqual(coordinator._viewer.changed_annotation_uids, [["ann-1"]])
        self.assertEqual(
            coordinator._viewer.changed_annotation_types,
            [[ANNOTATION_TYPE_TEXT]],
        )
        self.assertEqual(coordinator._sidebar.quantity_updates, 0)
        self.assertEqual(coordinator.main_window.menu_controller.updates, 1)

    def test_delayed_named_view_focus_rehydrates_same_uid_after_remote_change(self):
        stale_named_view = SimpleNamespace(uid="named-view-1", min_x=1.0)
        authoritative_annotation = BidAnnotation(
            uid="named-view-1",
            annotation_type=ANNOTATION_TYPE_NAMED_VIEW,
            page_uid="page-1",
            position=[20.0, 30.0, 40.0, 50.0],
            properties={"Text": "Authoritative"},
        )
        focused = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._pending_hotlink_page_uid = "page-1"
        coordinator._pending_hotlink_named_view = stale_named_view
        coordinator.project_data = SimpleNamespace(
            get_page_annotations=lambda page_uid: (
                [authoritative_annotation] if page_uid == "page-1" else []
            )
        )
        coordinator.plan_view = SimpleNamespace(
            current_page_uid="page-1",
            is_view_state_stable=True,
            isVisible=lambda: True,
            reveal_deferred_page_visual=lambda: None,
        )
        from ost_visualizer.presentation.coordinators import ui_event_coordinator

        with patch.object(
            ui_event_coordinator,
            "focus_plan_view_on_named_view",
            side_effect=lambda _plan_view, named_view: focused.append(named_view),
        ):
            self.assertTrue(
                coordinator._apply_pending_hotlink_named_view_focus(require_stable=True)
            )
        self.assertEqual(len(focused), 1)
        self.assertEqual(focused[0].name, "Authoritative")
        self.assertEqual((focused[0].min_x, focused[0].max_x), (20.0, 40.0))

    def test_delayed_named_view_focus_stops_after_remote_deletion(self):
        reveals = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._pending_hotlink_page_uid = "page-1"
        coordinator._pending_hotlink_named_view = SimpleNamespace(
            uid="deleted-named-view"
        )
        coordinator.project_data = SimpleNamespace(
            get_page_annotations=lambda _page_uid: []
        )
        coordinator.plan_view = SimpleNamespace(
            current_page_uid="page-1",
            is_view_state_stable=True,
            isVisible=lambda: True,
            reveal_deferred_page_visual=lambda: reveals.append(True),
        )
        from ost_visualizer.presentation.coordinators import ui_event_coordinator

        with patch.object(
            ui_event_coordinator,
            "focus_plan_view_on_named_view",
        ) as focus:
            self.assertFalse(
                coordinator._apply_pending_hotlink_named_view_focus(require_stable=True)
            )
        focus.assert_not_called()
        self.assertIsNone(coordinator._pending_hotlink_page_uid)
        self.assertIsNone(coordinator._pending_hotlink_named_view)
        self.assertEqual(reveals, [True])

    def test_bid_load_suspends_each_3d_surface_and_cancels_without_empty_publish(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        embedded = FakeMeshReceiver()
        detached = FakeMeshReceiver()
        visualization = FakeVisualization()
        configure_mesh_state(
            coordinator,
            opengl_viewer=embedded,
            mesh_window=detached,
            visualization=visualization,
        )
        coordinator._last_mesh_scene = mesh_publication(
            ("old-vertices", "old-normals", "old-indices", "old-colors"),
            scene_identity(BidRef("a.mdb", "old"), 1),
            {"page-1": 1.0},
        )
        target = BidRef("a.mdb", "new")
        coordinator._begin_mesh_views_for_bid_load(target)
        self.assertEqual(embedded.scene_loads, [target])
        self.assertEqual(detached.scene_loads, [target])
        self.assertEqual(visualization.cancelled_mesh_refreshes, 1)
        self.assertEqual(visualization.mesh_pages, [])
        self.assertIsNone(coordinator._last_mesh_scene)

    def test_detached_mesh_close_during_load_skips_callback_and_reopen_replays_final(
        self,
    ):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        active_ref = BidRef("a.mdb", "bid-1")
        coordinator.ui_state_manager = FakeUiState()
        coordinator.ui_state_manager.get_selected_bid_ref = lambda: active_ref
        coordinator.project_data = FakeProjectData()
        coordinator._nav = FakeNav()
        coordinator.ui_access_manager = FakeMeshAccess()
        coordinator._plan_view_signaler = FakeMeshPlanSignaler()
        embedded = FakeMeshReceiver(visible=True)
        closing_detached = FakeMeshReceiver(visible=True)
        configure_mesh_state(
            coordinator,
            view_index=0,
            opengl_viewer=embedded,
            mesh_window=closing_detached,
        )
        coordinator._last_mesh_scene = None
        coordinator._begin_mesh_views_for_bid_load(active_ref)
        embedded.prepare_scene_refresh(active_ref, ["page-1"])
        closing_detached.prepare_scene_refresh(active_ref, ["page-1"])
        closing_detached.visible = False
        coordinator._on_native_scene_updated(
            geometries=[],
            scene_identity=scene_identity(active_ref, 40),
            scene_failed=False,
        )
        self.assertEqual(len(embedded.mesh_calls), 1)
        self.assertEqual(closing_detached.mesh_calls, [])
        reopened = FakeMeshReceiver(visible=True)
        coordinator._replay_mesh_if_current(reopened)
        self.assertEqual(len(reopened.mesh_calls), 1)

    def test_condition_selection_in_3d_does_not_enter_place_mode(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        highlighted = []

        class UiState:
            highlighted_condition_uids = set()

            def set_highlighted_conditions(self, uids):
                self.highlighted_condition_uids = set(uids)
                highlighted.append(set(uids))

            def clear_place_condition(self):
                self.place_condition_uid = None

        class ProjectData:
            def get_bid_conditions(self):
                return {"c1": type("Condition", (), {"layer_visible": True})()}

        class Sidebar:
            def get_selected_condition_uids(self):
                return ["c1"]

        class PlanView:
            def __init__(self):
                self.modes = []

            def reset_ctrl_held(self):
                pass

            def set_cursor_mode(self, mode):
                self.modes.append(mode)

        coordinator.ui_state_manager = UiState()
        coordinator.project_data = ProjectData()
        coordinator.conditions_sidebar = Sidebar()
        coordinator.plan_view = PlanView()
        coordinator._placement = FakePlacement()
        coordinator._toolbar = FakeToolbar()
        coordinator._toolbar.takeoff_2d_active = False
        coordinator._on_condition_selected("c1")
        self.assertEqual(coordinator._placement.enter_calls, [])
        self.assertEqual(coordinator.plan_view.modes, ["select"])
        self.assertEqual(coordinator._toolbar.select_checked, 1)
        self.assertEqual(highlighted, [{"c1"}])

    def test_matching_explicit_condition_remains_explicit_after_takeoff_deselect(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)

        class UiState:
            def __init__(self):
                self.highlighted_condition_uids = set()

            def set_highlighted_conditions(self, uids):
                self.highlighted_condition_uids = set(uids)

        class Sidebar:
            def __init__(self):
                self.highlights = []
                self.selected = set()

            def highlight_conditions(self, uids, reveal=True):
                self.selected = set(uids)
                self.highlights.append(set(uids))

            def get_selected_condition_uids(self):
                return sorted(self.selected)

        coordinator.ui_state_manager = UiState()
        coordinator.project_data = SimpleNamespace(
            get_all_takeoffs=lambda: [
                type("Takeoff", (), {"uid": "t1", "condition_uid": "c1"})()
            ]
        )
        coordinator.conditions_sidebar = Sidebar()
        coordinator.plan_view = None
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator._placement = FakePlacement()
        coordinator._toolbar = FakeToolbar()
        coordinator._tab_widget = FakeTabWidget(index=1)
        coordinator._nav = SimpleNamespace(is_refreshing=False)
        coordinator._selected_takeoff_uids = ()
        coordinator._selection_projected_condition_uids = set()
        coordinator.highlight_sidebar({"c1"})
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1"])
        coordinator._sync_selection(coordinator._SOURCE_2D, [])
        self.assertEqual(coordinator.conditions_sidebar.selected, {"c1"})
        self.assertEqual(
            coordinator.ui_state_manager.highlighted_condition_uids, {"c1"}
        )
        self.assertEqual(coordinator._selection_projected_condition_uids, set())
        self.assertEqual(coordinator.conditions_sidebar.highlights, [{"c1"}])

    def test_passive_sidebar_restore_preserves_only_matching_takeoff_ownership(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)

        class UiState:
            highlighted_condition_uids = set()

            def set_highlighted_conditions(self, uids):
                self.highlighted_condition_uids = set(uids)

        class Sidebar:
            def __init__(self):
                self.selected = set()

            def highlight_conditions(self, uids, reveal=True):
                self.selected = set(uids)

        coordinator.ui_state_manager = UiState()
        coordinator.conditions_sidebar = Sidebar()
        coordinator._nav = SimpleNamespace(is_refreshing=False)
        coordinator._toolbar = FakeToolbar()
        coordinator._selection_projected_condition_uids = {"c1"}
        coordinator._restore_sidebar_highlight({"c1"})
        self.assertEqual(coordinator._selection_projected_condition_uids, {"c1"})
        self.assertEqual(coordinator.conditions_sidebar.selected, {"c1"})
        coordinator._restore_sidebar_highlight({"c2"})
        self.assertEqual(coordinator._selection_projected_condition_uids, set())
        self.assertEqual(coordinator.conditions_sidebar.selected, {"c2"})

    def test_takeoff_workspace_hydration_restores_sidebar_highlight_without_reveal(
        self,
    ):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        bid_ref = BidRef("active.mdb", "bid-1")
        reveal_args = []

        class UiState:
            highlighted_condition_uids = {"c1"}
            selected_page_uids = []
            active_page_uid = None
            selected_area_uid = ""

            def get_selected_bid_ref(self):
                return bid_ref

        class ProjectData:
            def get_bid_conditions(self):
                return {"c1": object()}

            def get_area_uids_with_takeoff(self):
                return []

            def get_selected_page_uids(self):
                return []

            def get_page(self, _page_uid):
                return None

            def get_last_selected_page_uid(self):
                return None

        class TakeoffSidebar:
            def get_first_page_uid(self):
                return None

            def restore_selection(self, _page_uids, _active_uid):
                pass

        class Sidebar:
            def load_bid_layers_sidebar(self):
                pass

            def load_conditions_sidebar(self):
                pass

            def update_conditions_quantities(self):
                pass

        class MainWindow:
            def notify_takeoff_workspace_activated(self):
                pass

        coordinator.ui_state_manager = UiState()
        coordinator.project_data = ProjectData()
        coordinator.takeoff_sidebar = TakeoffSidebar()
        coordinator._sidebar = Sidebar()
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: False
        )
        coordinator.main_window = MainWindow()
        coordinator._page_settings_bar = None
        coordinator._takeoff_workspace_bid_ref = None
        coordinator._pending_takeoff_page_uids = None
        coordinator._pending_takeoff_active_page_uid = None
        coordinator._pending_takeoff_selected_area_uid = ""
        coordinator._pending_takeoff_place_condition_uid = None
        coordinator._pending_takeoff_place_condition_uids = []
        coordinator._load_takeoff_sidebar = lambda _bid_ref: None
        coordinator._load_condition_summary = lambda: None
        coordinator._sync_embedded_renderer_exposure = lambda: None
        coordinator._nav = type("Nav", (), {"is_refreshing": False})()
        coordinator._restore_sidebar_highlight = (
            lambda _uids, reveal=True: reveal_args.append(reveal)
        )
        coordinator.handle_active_page_changed = lambda _page_uid: None
        coordinator._activate_takeoff_workspace()
        self.assertEqual(reveal_args, [False])

    def test_sql_layer_rename_flush_failure_restores_hydrated_sidebar(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        calls = []
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("sql-database", "8")
        )
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: True
        )
        coordinator._flush_deferred_for_file = lambda _database_id: False
        coordinator._sidebar = SimpleNamespace(
            load_bid_layers_sidebar=lambda: calls.append("database"),
            load_bid_layers_sidebar_from_memory=lambda: calls.append("memory"),
        )
        coordinator._on_layer_renamed("layer-1", "Updated")
        self.assertEqual(calls, ["memory"])

    def test_queued_layer_failure_uses_canonical_error_boundary(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        calls = []
        result = SimpleNamespace(
            database_id="sql-database",
            outcome_status=MutationOutcomeStatus.CONFLICT,
            message="conflict",
        )
        coordinator._is_cleaning_up = False
        coordinator._sidebar = SimpleNamespace(
            load_bid_layers_sidebar_from_memory=lambda: calls.append("memory")
        )
        coordinator.present_queued_mutation_error = (
            lambda database_id, title, presented: calls.append(
                (database_id, title, presented)
            )
        )
        coordinator._on_queued_layer_write_complete(result)
        self.assertEqual(calls[0], "memory")
        self.assertEqual(calls[1], ("sql-database", "Layer Update", result))

    def test_access_layer_delete_failure_restores_sidebar_and_reports_error(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        calls = []
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("db.mdb", "8")
        )
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: False,
            delete_layer=lambda _database_id, _layer_uid: False,
        )
        coordinator._flush_deferred_for_file = lambda _database_id: True
        coordinator._sidebar = SimpleNamespace(
            load_bid_layers_sidebar=lambda: calls.append("reload")
        )
        coordinator.main_window = object()
        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator."
            "show_critical"
        ) as show_error:
            coordinator._on_layer_deleted("layer-1")
        self.assertEqual(calls, ["reload"])
        show_error.assert_called_once()
        self.assertEqual(show_error.call_args.args[1], "Delete Layer")

    def test_sql_layer_delete_failure_reports_delete_operation(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        queued = {}
        calls = []
        result = SimpleNamespace(
            database_id="sql-database",
            outcome_status=MutationOutcomeStatus.CONFLICT,
            message="conflict",
        )

        def queue_delete(_database_id, _bid_uid, _layer_uid, callback):
            queued["callback"] = callback

        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("sql-database", "8")
        )
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: True,
            queue_layer_delete=queue_delete,
        )
        coordinator._flush_deferred_for_file = lambda _database_id: True
        coordinator._sidebar = SimpleNamespace(
            load_bid_layers_sidebar_from_memory=lambda: calls.append("reload")
        )
        coordinator._is_cleaning_up = False
        coordinator.present_queued_mutation_error = (
            lambda database_id, title, presented: calls.append(
                (database_id, title, presented)
            )
        )
        coordinator._on_layer_deleted("layer-1")
        queued["callback"](result)
        self.assertEqual(calls[0], "reload")
        self.assertEqual(calls[1], ("sql-database", "Delete Layer", result))

    def test_projection_recovery_does_not_open_a_premature_modal_error(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator._prepare_for_modal_mutation_error = lambda _database_id: self.fail(
            "Automatic projection recovery must not normalize for a modal dialog"
        )
        result = SimpleNamespace(
            outcome_status=MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
            message="recovering",
        )
        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator.show_warning",
            side_effect=AssertionError("recovery must not show a warning yet"),
        ):
            coordinator.present_queued_mutation_error(
                "sql-database",
                "Layer Update",
                result,
            )

    def test_bid_area_save_waits_for_recovery_before_completing_dialog(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        callbacks = []
        completed = []
        errors = []
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        coordinator._project_write_service = SimpleNamespace(
            queue_bid_areas_save=(
                lambda _database_id, _bid_uid, _changes, callback: callbacks.append(
                    callback
                )
            )
        )
        coordinator.present_queued_mutation_error = lambda *_args: errors.append(_args)
        bid_ref = BidRef("sql-database", "8")
        self.assertTrue(
            coordinator._save_bid_areas_async(
                bid_ref,
                object(),
                lambda success, uid_map: completed.append((success, uid_map)),
            )
        )
        for status in (
            MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        ):
            callbacks[0](
                SimpleNamespace(outcome_status=status, authoritative_result=None)
            )
        self.assertEqual(completed, [])
        self.assertEqual(errors, [])
        callbacks[0](
            SimpleNamespace(
                outcome_status=MutationOutcomeStatus.COMMITTED,
                authoritative_result=SimpleNamespace(
                    created_uid_maps=(("areas", (("new_0", "area-2"),)),)
                ),
            )
        )
        self.assertEqual(completed, [(True, {"new_0": "area-2"})])
        self.assertEqual(errors, [])

    def test_late_takeoff_selection_signal_after_cleanup_is_ignored(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._placement = None
        coordinator._nav = None
        coordinator._on_takeoff_selection_changed(["t1"])

    def test_cleanup_is_idempotent_after_dependencies_are_released(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        visualization = FakeVisualization()
        coordinator._is_cleaning_up = False
        coordinator.visualization_service = visualization
        coordinator._last_mesh_scene = None
        coordinator._pending_3d_takeoff_uids_by_bid = {}
        coordinator._mesh_scene_dirty = False
        coordinator._dirty_mesh_page_uids = set()
        coordinator._pending_dirty_mesh_refresh = False
        coordinator._plan_view_handler = None
        coordinator._view_stack = None
        coordinator._tab_widget = None
        coordinator._undo_service = None
        coordinator._subscriptions = []
        coordinator.event_bus = None
        coordinator._plan_view_signaler = None
        coordinator._menu_state_signaler = None
        coordinator._bid_data_cache = {}
        coordinator._mesh_window = None
        coordinator._mesh_window_action = None
        coordinator._placement = None
        coordinator.opengl_viewer = None
        coordinator.takeoff_sidebar = None
        coordinator.plan_view = None
        coordinator._sidebar = None
        coordinator._viewer = None
        coordinator._toolbar = None
        coordinator.main_window = None
        coordinator.ui_state_manager = None
        coordinator.ui_access_manager = None
        coordinator.project_data = None
        coordinator.project_operations = ImmediateNavigationOperations()
        coordinator._color_service = None
        coordinator._icon_provider = None
        coordinator._project_write_service = None
        coordinator._project_read_service = None
        coordinator.conditions_sidebar = None
        coordinator.condition_summary_tab = None
        coordinator._condition_handler = None
        coordinator._deferred_persistence = None
        status_panel = _CollaborationStatusPanel()
        status_panel.set_page_info("Loading bid pages…")
        status_panel.set_collaboration_state("healthy", "Connected")
        status_panel.set_collaboration_mutation_state("recovering", 1, "Recovering")
        coordinator._status_panel = status_panel
        coordinator.cleanup()
        coordinator.cleanup()
        self.assertEqual(visualization.cancelled_mesh_refreshes, 1)
        self.assertEqual(status_panel.page_info, "")
        self.assertEqual(status_panel.presence_states[-1], [])
        self.assertEqual(status_panel.mutation_states[-1], ("", 0, ""))
        self.assertEqual(status_panel.states[-1], ("stopped", ""))
        self.assertIsNone(coordinator._status_panel)

    def test_cleanup_releases_active_plan_interaction_before_view_cleanup(self):
        sequence = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.visualization_service = FakeVisualization()
        coordinator._last_mesh_scene = None
        coordinator._pending_3d_takeoff_uids_by_bid = {}
        coordinator._mesh_scene_dirty = False
        coordinator._dirty_mesh_page_uids = set()
        coordinator._pending_dirty_mesh_refresh = False
        coordinator._plan_view_handler = SimpleNamespace(
            invalidate_pending_takeoff_placements=lambda: sequence.append(
                "invalidate-placement"
            ),
            prepare_for_authoritative_refresh=lambda: sequence.append(
                "release-interaction"
            ),
        )
        coordinator._view_stack = None
        coordinator._tab_widget = None
        coordinator._undo_service = None
        coordinator._subscriptions = []
        coordinator.event_bus = None
        coordinator._plan_view_signaler = None
        coordinator._menu_state_signaler = None
        coordinator._bid_data_cache = {}
        coordinator._mesh_window = None
        coordinator._mesh_window_action = None
        coordinator._placement = None
        coordinator.opengl_viewer = None
        coordinator.takeoff_sidebar = None
        coordinator.plan_view = SimpleNamespace(
            cleanup=lambda: sequence.append("plan-cleanup")
        )
        coordinator._sidebar = None
        coordinator._viewer = None
        coordinator._toolbar = None
        coordinator.main_window = None
        coordinator.ui_state_manager = None
        coordinator.ui_access_manager = None
        coordinator.project_data = None
        coordinator.project_operations = ImmediateNavigationOperations()
        coordinator._color_service = None
        coordinator._icon_provider = None
        coordinator._project_write_service = None
        coordinator._project_read_service = None
        coordinator.conditions_sidebar = None
        coordinator.condition_summary_tab = None
        coordinator._condition_handler = None
        coordinator._deferred_persistence = None
        coordinator._status_panel = None
        coordinator.cleanup()
        self.assertEqual(
            sequence,
            ["release-interaction", "invalidate-placement", "plan-cleanup"],
        )

    def test_2d_and_3d_page_information_use_the_same_tab_aware_projection(self):
        coordinator = navigation_status_coordinator(tab_index=TAB_INDEX_TAKEOFF)
        coordinator.project_data.pages["page-2"] = SimpleNamespace(name="Page Two")
        coordinator.ui_state_manager.selected_page_uids = ["page-1", "page-2"]
        coordinator.ui_state_manager.active_page_uid = "page-2"
        coordinator._view_stack.setCurrentIndex(1)
        coordinator._sync_page_info_status()
        self.assertEqual(coordinator._status_panel.page_info, "Page Two")
        coordinator._view_stack.setCurrentIndex(0)
        coordinator._sync_page_info_status()
        self.assertEqual(coordinator._status_panel.page_info, "Page One, Page Two")
        coordinator._tab_widget.setCurrentIndex(TAB_INDEX_PROJECTS)
        coordinator._sync_page_info_status()
        self.assertEqual(coordinator._status_panel.page_info, "")

    def test_bid_deselection_clears_ready_page_information(self):
        coordinator = navigation_status_coordinator(tab_index=TAB_INDEX_TAKEOFF)
        coordinator.ui_state_manager.bid_ref = BidRef("sql-database", "bid-1")
        coordinator.ui_state_manager.selected_page_uids = ["page-1"]
        coordinator.ui_state_manager.active_page_uid = "page-1"
        coordinator._sync_page_info_status()
        self.assertEqual(coordinator._status_panel.page_info, "Page One")
        coordinator.handle_bid_selection(None)
        self.assertEqual(coordinator._status_panel.page_info, "")
        self.assertEqual(coordinator._status_panel.presence_states[-1], [])
        self.assertEqual(coordinator._status_panel.mutation_states[-1], ("", 0, ""))
        self.assertEqual(coordinator._status_panel.states[-1], ("stopped", ""))

    def test_file_selection_flush_failure_keeps_current_bid_context(self):
        coordinator = navigation_status_coordinator()
        old_ref = BidRef("sql-database", "old-bid")
        coordinator.ui_state_manager.bid_ref = old_ref
        sequence = []
        coordinator._save_current_page_view_state = lambda: sequence.append("save")
        coordinator._flush_deferred_for_file = (
            lambda file_path: sequence.append(("flush", file_path)) or False
        )
        coordinator._prepare_plan_for_authoritative_refresh = lambda: sequence.append(
            "cancel"
        )
        coordinator._on_file_selected(
            file_path="other-sql-database",
            is_database_root=True,
        )
        self.assertEqual(sequence, ["save", ("flush", old_ref.file_path)])
        self.assertEqual(coordinator.ui_state_manager.get_selected_bid_ref(), old_ref)

    def test_file_selection_clears_undo_owner_after_resetting_selection(self):
        old_ref = BidRef("old.mdb", "old-bid")

        class UiState:
            def __init__(self):
                self.bid_ref = old_ref
                self.database_selected = None
                self.project_uid = None

            def get_selected_bid_ref(self):
                return self.bid_ref

            def reset_selections(self):
                self.bid_ref = None

            def set_database_selected(self, selected, file_path=None):
                self.database_selected = (selected, file_path)

            def set_project_uid(self, project_uid):
                self.project_uid = project_uid

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeMainWindow()
        coordinator.project_operations = ImmediateNavigationOperations()
        coordinator._sql_collaboration = FakeSqlCollaboration()
        coordinator._plan_view_handler = None
        coordinator._status_panel = None
        coordinator.ui_state_manager = UiState()
        clear_bid_calls = []
        coordinator.project_data = type(
            "ProjectData",
            (),
            {
                "clear_bid": lambda _self: clear_bid_calls.append(True),
                "deselect_pages": lambda _self: None,
            },
        )()
        coordinator._undo_service = FakeUndo()
        coordinator._placement = FakePlacement()
        coordinator._viewer = FakeUnloadViewer()
        coordinator.visualization_service = FakeVisualization()
        coordinator.ui_access_manager = FakeAccess()
        coordinator._nav = FakeNav()
        coordinator._update_export_menu_state = lambda: None
        coordinator._save_current_page_view_state = lambda: None
        coordinator._flush_deferred_for_file = lambda _file_path: True
        coordinator._clear_mesh_views_for_scene_update = lambda **_call_options: None
        coordinator._reset_takeoff_workspace_state = lambda: None
        coordinator._set_takeoff_tab_visible = lambda _visible: None
        coordinator._on_file_selected(file_path="new.mdb", is_database_root=True)
        self.assertIsNone(coordinator.ui_state_manager.get_selected_bid_ref())
        self.assertEqual(coordinator._undo_service.active, [None])
        self.assertEqual(clear_bid_calls, [True])

    def test_page_settings_bar_sync_stores_validated_area_uid(self):
        class UiState:
            selected_area_uid = ""

        class ProjectData:
            def get_page(self, page_uid):
                return Page(uid=page_uid, name="Page 1")

            def get_page_area_selections(self):
                return {"page-1": "deleted-area"}

            def get_area_uids_with_takeoff_for_page(self, _page_uid):
                return set()

        class PageSettingsBar:
            def __init__(self):
                self.loaded = []

            def load_page(
                self,
                page_uid,
                sf1,
                sf2,
                selected_area_uid,
                areas_with_takeoff=None,
            ):
                self.loaded.append(
                    (page_uid, sf1, sf2, selected_area_uid, areas_with_takeoff)
                )

            def get_selected_area_uid(self):
                return ""

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = UiState()
        coordinator.project_data = ProjectData()
        coordinator._page_settings_bar = PageSettingsBar()
        coordinator._update_page_settings_bar("page-1")
        self.assertEqual(coordinator._page_settings_bar.loaded[0][3], "deleted-area")
        self.assertEqual(coordinator.ui_state_manager.selected_area_uid, "")

    def test_layer_insert_completion_rejects_same_uid_bid_replacement(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        bid_ref = BidRef("sql-database", "7")
        original_bid = object()
        current_bid = [original_bid]
        queued = {}
        pending_selections = []
        sidebar = SimpleNamespace(
            set_pending_selection=lambda uid: pending_selections.append(uid),
        )

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return True

            @staticmethod
            def queue_layer_insert(
                database_id,
                bid_uid,
                name,
                after_sequence,
                callback,
            ):
                queued["callback"] = callback
                return 1

        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda feature: feature == Feature.EDIT_PAGE_SETTINGS
        )
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: bid_ref
        )
        coordinator.project_data = SimpleNamespace(get_bid=lambda _ref: current_bid[0])
        coordinator._sidebar = SimpleNamespace(
            bid_layers_sidebar=sidebar,
            load_bid_layers_sidebar=lambda: None,
            load_bid_layers_sidebar_from_memory=lambda: None,
        )
        coordinator._project_write_service = WriteService()
        coordinator._flush_deferred_for_file = lambda _file_path: True
        coordinator._is_cleaning_up = False
        coordinator.main_window = None
        coordinator.present_queued_mutation_error = lambda *_args, **_kwargs: None
        coordinator._on_layer_added("New Layer", 3)
        current_bid[0] = object()
        self.assertIsNot(current_bid[0], original_bid)
        queued["callback"](
            QueuedMutationResult(
                database_id="sql-database",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000701",
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("layer-new",),
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=("layer-new",),
                ),
                commit_attempted=True,
            )
        )
        self.assertEqual(pending_selections, [])

    def test_file_refresh_rebuilds_tree_from_reloaded_hierarchy(self):
        class ProjectData:
            def get_hierarchy(self):
                return HierarchyData(
                    loaded_files=[
                        HierarchyFileEntry(
                            file_path="active.mdb",
                            display_name="active.mdb",
                            bid_projects={
                                "1": HierarchyProjectInfo(
                                    name="Deleted Bids",
                                    bids=[HierarchyBidInfo(uid="bid-1", name="Moved")],
                                ),
                                "project-2": HierarchyProjectInfo(
                                    name="Original",
                                    bids=[],
                                ),
                            },
                        )
                    ]
                )

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.main_window = FakeUnloadMainWindow()
        coordinator.project_data = ProjectData()
        coordinator._sql_collaboration = FakeSqlCollaboration()
        coordinator._status_panel = None
        coordinator._cache_bid_data = lambda _loaded_files: None
        coordinator._do_file_refresh()
        loaded_file = coordinator.main_window.project_view.loaded_files[0]
        projects = {project.uid: project for project in loaded_file.projects}
        self.assertEqual(projects["project-2"].bids, [])
        self.assertEqual([bid.uid for bid in projects["1"].bids], ["bid-1"])


class UIEventCoordinatorOnConditionsChangedTests(
    _UIEventCoordinatorTakeoffsChangedFixture
):
    """UIEventCoordinator._on_conditions_changed."""

    def test_condition_change_fields_control_mesh_refresh_and_undo_ownership(self):
        bid_ref = BidRef("sql-database", "bid-1")
        ui_state = UIStateManager(
            SimpleNamespace(
                display_modes_synced=False,
                display_mode_3d="condition",
                display_mode_2d="condition",
                grayscale_enabled=False,
            )
        )
        ui_state.set_bid_selection(bid_ref)
        ui_state.set_highlighted_conditions({"c1", "deleted"})
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeMainWindow()
        coordinator._status_panel = None
        coordinator.ui_state_manager = ui_state
        coordinator.plan_view = None
        coordinator._plan_view_handler = None
        coordinator._placement = FakePlacement()
        mesh_refreshes = []
        coordinator.project_data = SimpleNamespace(
            get_bid_conditions=lambda: {"c1": object()},
            get_selected_page_uids=lambda: ["page-1"],
        )
        undo_clears = []
        coordinator._undo_service = SimpleNamespace(
            clear=lambda: undo_clears.append(True)
        )
        summary_loads = []
        coordinator._sidebar = SimpleNamespace(
            refresh_conditions_from_memory=lambda: summary_loads.append(True)
        )
        coordinator._restore_sidebar_highlight = lambda _uids, reveal=False: None
        plan_refreshes = []
        coordinator._update_plan_view_for_active = lambda **kwargs: (
            plan_refreshes.append(kwargs)
        )
        coordinator._request_or_defer_mesh_refresh = (
            lambda pages: mesh_refreshes.append(list(pages))
        )
        coordinator._is_summary_tab_active = lambda: True
        coordinator._load_condition_summary = lambda: summary_loads.append(True)
        coordinator._update_export_menu_state = lambda: None
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["c1"],
            changed_fields=["name", "notes"],
        )
        self.assertEqual(ui_state.highlighted_condition_uids, {"c1"})
        self.assertEqual(mesh_refreshes, [])
        self.assertEqual(undo_clears, [])
        self.assertEqual(len(plan_refreshes), 1)
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["c1"],
            changed_fields=["notes"],
        )
        self.assertEqual(mesh_refreshes, [])
        self.assertEqual(len(plan_refreshes), 1)
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["c1"],
            changed_fields=["folder_uid"],
            change_operations=["update"],
        )
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["c2"],
            changed_fields=[],
            change_operations=["create"],
        )
        self.assertEqual(mesh_refreshes, [])
        self.assertEqual(len(plan_refreshes), 2)
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["c1"],
            changed_fields=["z_value"],
        )
        self.assertEqual(mesh_refreshes, [["page-1"]])
        self.assertEqual(undo_clears, [])
        self.assertEqual(len(plan_refreshes), 3)
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["c1"],
            changed_fields=["layer_uid"],
        )
        self.assertEqual(mesh_refreshes, [["page-1"], ["page-1"]])
        self.assertEqual(undo_clears, [])
        self.assertEqual(len(plan_refreshes), 4)
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["c1"],
            changed_fields=["name"],
            invalidates_undo=True,
        )
        self.assertEqual(mesh_refreshes, [["page-1"], ["page-1"]])
        self.assertEqual(undo_clears, [True])
        self.assertEqual(len(plan_refreshes), 5)
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["c1"],
            changed_fields=[],
            change_operations=["delete"],
            invalidates_undo=True,
        )
        self.assertEqual(
            mesh_refreshes,
            [["page-1"], ["page-1"], ["page-1"]],
        )
        self.assertEqual(undo_clears, [True, True])
        self.assertEqual(len(plan_refreshes), 6)
        self.assertEqual(len(summary_loads), 8)

    def test_condition_change_rebuilds_summary_once_through_sidebar_projection(self):
        bid_ref = BidRef("sql-database", "bid-1")
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeMainWindow()
        coordinator._status_panel = None
        coordinator._placement = FakePlacement()
        coordinator.ui_state_manager = SimpleNamespace(
            highlighted_condition_uids=set(),
            place_condition_uid=None,
            place_condition_uids=[],
            get_selected_bid_ref=lambda: bid_ref,
            set_highlighted_conditions=lambda _uids: None,
        )
        coordinator.project_data = SimpleNamespace(
            get_bid_conditions=lambda: {"c1": Condition(uid="c1")},
            get_selected_page_uids=lambda: ["page-1"],
        )
        coordinator._undo_service = None
        summary_rebuilds = []
        coordinator._sidebar = SimpleNamespace(
            refresh_conditions_from_memory=lambda: summary_rebuilds.append("sidebar")
        )
        coordinator._restore_sidebar_highlight = lambda _uids, reveal=False: None
        coordinator._update_plan_view_for_active = lambda **_kwargs: None
        coordinator._request_or_defer_mesh_refresh = lambda _pages: None
        coordinator._is_summary_tab_active = lambda: True
        coordinator._load_condition_summary = lambda: summary_rebuilds.append(
            "explicit"
        )
        coordinator._update_export_menu_state = lambda: None
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["c1"],
            changed_fields=["notes"],
        )
        self.assertEqual(summary_rebuilds, ["sidebar"])
        self.assertEqual(
            coordinator.main_window.project_view.bid_content_counts,
            [(bid_ref, {"condition_count": 1})],
        )

    def test_remote_condition_deletion_exits_placement_owned_by_deleted_condition(self):
        bid_ref = BidRef("sql-database", "bid-1")
        ui_state = UIStateManager(
            SimpleNamespace(
                display_modes_synced=False,
                display_mode_3d="condition",
                display_mode_2d="condition",
                grayscale_enabled=False,
            )
        )
        ui_state.set_bid_selection(bid_ref)
        ui_state.place_condition_uid = "deleted-condition"
        ui_state.set_place_condition_uids(["remaining-condition", "deleted-condition"])
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeMainWindow()
        coordinator.ui_state_manager = ui_state
        cancellation_order = []
        coordinator.plan_view = SimpleNamespace(
            has_active_remote_projection_blocker=lambda: True
        )
        coordinator._plan_view_handler = SimpleNamespace(
            prepare_for_authoritative_refresh=lambda: cancellation_order.append(
                "cancel"
            )
        )
        coordinator.project_data = SimpleNamespace(
            get_bid_conditions=lambda: {
                "remaining-condition": Condition(uid="remaining-condition")
            },
            get_selected_page_uids=lambda: ["page-1"],
        )
        coordinator._undo_service = None
        coordinator._sidebar = SimpleNamespace(
            refresh_conditions_from_memory=lambda: None
        )
        coordinator._restore_sidebar_highlight = lambda _uids, reveal=False: None
        coordinator._update_plan_view_for_active = lambda **_kwargs: None
        coordinator._request_or_defer_mesh_refresh = lambda _pages: None
        coordinator._update_export_menu_state = lambda: None

        class ClearingPlacement(FakePlacement):
            def reconcile_authoritative_conditions(
                self, *, accept_reconstructed_conditions=False
            ):
                _ = accept_reconstructed_conditions
                super().reconcile_authoritative_conditions()
                self.force_exit()
                ui_state.clear_place_condition()
                return False

        coordinator._placement = ClearingPlacement()
        select_mode_calls = []
        coordinator._set_plan_select_mode = lambda: select_mode_calls.append(True)
        coordinator._toolbar = FakeToolbar()
        coordinator._bid_clipboard = None
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["deleted-condition"],
            changed_fields=[],
            change_operations=["delete"],
            invalidates_undo=True,
        )
        self.assertEqual(cancellation_order, ["cancel"])
        self.assertEqual(coordinator._placement.force_exit_count, 1)
        self.assertEqual(select_mode_calls, [True])
        self.assertIsNone(ui_state.place_condition_uid)
        self.assertEqual(ui_state.place_condition_uids, [])

    def test_condition_refresh_reprojects_takeoff_enablement_for_restored_selection(
        self,
    ):
        bid_ref = BidRef("active.mdb", "bid-1")
        conditions = {
            "condition-1": Condition(
                uid="condition-1",
                layer_visible=False,
                condition_type=Condition.TYPE_AREA,
            )
        }

        class UiState:
            highlighted_condition_uids = {"condition-1"}

            @staticmethod
            def get_selected_bid_ref():
                return bid_ref

            def set_highlighted_conditions(self, uids):
                self.highlighted_condition_uids = set(uids)

            def set_page_selection(self, page_uids):
                self.selected_page_uids = list(page_uids)

        class Sidebar:
            def __init__(self):
                self.selected = set()

            def highlight_conditions(self, uids, reveal=True):
                _ = reveal
                self.selected = set(uids)

            def get_selected_condition_uids(self):
                return sorted(self.selected)

        class Toolbar:
            def __init__(self, sidebar):
                self.sidebar = sidebar
                self.place_enabled = True
                self.refresh_count = 0

            def refresh(self):
                self.refresh_count += 1
                selected = self.sidebar.get_selected_condition_uids()
                self.place_enabled = bool(
                    selected and conditions[selected[0]].layer_visible
                )

        sidebar = Sidebar()
        toolbar = Toolbar(sidebar)
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeMainWindow()
        coordinator.ui_state_manager = UiState()
        coordinator.project_data = SimpleNamespace(
            get_bid_conditions=lambda: conditions,
            get_selected_page_uids=lambda: ["page-1"],
        )
        coordinator.conditions_sidebar = sidebar
        coordinator._selection_projected_condition_uids = set()
        coordinator._nav = SimpleNamespace(is_refreshing=False)
        coordinator._placement = SimpleNamespace(
            reconcile_authoritative_conditions=lambda **_kwargs: True
        )
        coordinator._toolbar = toolbar
        coordinator._undo_service = None
        coordinator._sidebar = SimpleNamespace(
            refresh_conditions_from_memory=lambda: None
        )
        coordinator._update_plan_view_for_active = lambda **_kwargs: None
        coordinator._request_or_defer_mesh_refresh = lambda _pages: None
        coordinator._update_export_menu_state = lambda: None
        coordinator.plan_view = None
        coordinator._plan_view_handler = None
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["condition-1"],
            changed_fields=["layer_uid"],
            change_operations=["update"],
            local_completion=True,
        )
        self.assertEqual(sidebar.selected, {"condition-1"})
        self.assertFalse(toolbar.place_enabled)
        self.assertEqual(toolbar.refresh_count, 1)

    def test_authoritative_condition_updates_preserve_active_takeoff_tool(self):
        bid_ref = BidRef("active.mdb", "bid-1")

        class UiState:
            active_page_uid = "page-1"
            place_condition_uid = None
            highlighted_condition_uids = {"condition-1"}
            state = SimpleNamespace(
                display_mode_2d="condition",
                grayscale_enabled=False,
            )

            def __init__(self):
                self.place_condition_uids = []

            @staticmethod
            def get_selected_bid_ref():
                return bid_ref

            def set_place_condition_uids(self, uids):
                self.place_condition_uids = list(uids)

            def clear_place_condition(self):
                self.place_condition_uid = None
                self.place_condition_uids = []

            def set_highlighted_conditions(self, uids):
                self.highlighted_condition_uids = set(uids)

        class PlanView:
            def __init__(self):
                self.cursor_mode = "select"
                self.cancel_calls = 0

            def activate_place_for_condition(self, _condition_uid, _condition_uids):
                self.cursor_mode = "place"
                return True

            @staticmethod
            def update_color_map(_color_map):
                pass

            def cancel_place_mode(self):
                self.cursor_mode = "select"
                self.cancel_calls += 1

            @staticmethod
            def reset_ctrl_held():
                pass

            @staticmethod
            def has_active_remote_projection_blocker():
                return False

            def set_cursor_mode(self, mode):
                self.cursor_mode = mode

        conditions = {
            "condition-1": Condition(
                uid="condition-1",
                name="Before",
                layer_visible=True,
                condition_type=Condition.TYPE_AREA,
            )
        }
        ui_state = UiState()
        plan_view = PlanView()
        project_data = SimpleNamespace(
            get_bid_conditions=lambda: conditions,
            get_page_takeoffs=lambda _page_uid: [],
            get_selected_page_uids=lambda: ["page-1"],
        )
        placement = PlacementCoordinator(
            ui_state_manager=ui_state,
            ui_access_manager=SimpleNamespace(
                is_allowed=lambda feature: feature == Feature.PLACE_PLAN_ITEMS,
                set_area_placement_active=lambda _active, *, surface_id: None,
            ),
            color_service=SimpleNamespace(
                get_color_mapping=lambda *_args, **_kwargs: (None, {})
            ),
            project_data=project_data,
        )
        placement._plan_view = plan_view
        self.assertTrue(placement.enter("condition-1", ["condition-1"]))
        # A normal successful local save reloads authoritative Condition objects.
        conditions["condition-1"] = Condition(
            uid="condition-1",
            name="After",
            layer_visible=True,
            condition_type=Condition.TYPE_AREA,
        )
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeMainWindow()
        coordinator.ui_state_manager = ui_state
        coordinator.project_data = project_data
        coordinator.plan_view = plan_view
        coordinator._plan_view_handler = None
        coordinator._placement = placement
        coordinator._toolbar = FakeToolbar()
        coordinator._undo_service = None
        coordinator._sidebar = SimpleNamespace(
            refresh_conditions_from_memory=lambda: None
        )
        coordinator._restore_sidebar_highlight = lambda _uids, reveal=False: None
        coordinator._update_plan_view_for_active = lambda **_kwargs: None
        coordinator._request_or_defer_mesh_refresh = lambda _pages: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["condition-1"],
            changed_fields=["name"],
            change_operations=["update"],
            invalidates_undo=False,
            local_completion=True,
        )
        self.assertTrue(placement.is_active)
        self.assertEqual(ui_state.place_condition_uid, "condition-1")
        self.assertEqual(plan_view.cursor_mode, "place")
        self.assertEqual(plan_view.cancel_calls, 0)
        conditions["condition-1"] = Condition(
            uid="condition-1",
            name="After",
            condition_type=Condition.TYPE_AREA,
            ref_no=2,
        )
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["condition-1"],
            changed_fields=["ref_no"],
            change_operations=["reorder"],
            local_completion=True,
        )
        self.assertTrue(placement.is_active)
        self.assertEqual(plan_view.cursor_mode, "place")
        self.assertEqual(plan_view.cancel_calls, 0)
        # A geometry-setting edit keeps the same placement kind; subsequent
        # takeoffs use the reconstructed Condition's new dimensions.
        conditions["condition-1"] = Condition(
            uid="condition-1",
            name="After",
            width=24.0,
            layer_visible=True,
            condition_type=Condition.TYPE_AREA,
        )
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["condition-1"],
            changed_fields=["width"],
            change_operations=["update"],
            invalidates_undo=False,
            local_completion=True,
        )
        self.assertTrue(placement.is_active)
        self.assertEqual(plan_view.cursor_mode, "place")
        # Folder and visible-Layer changes replace the authoritative object but
        # do not invalidate the placement geometry/type contract.
        conditions["condition-1"] = Condition(
            uid="condition-1",
            name="After",
            folder_uid="folder-2",
            layer_uid="layer-2",
            layer_visible=True,
            condition_type=Condition.TYPE_AREA,
        )
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["condition-1"],
            changed_fields=["folder_uid", "layer_uid"],
            change_operations=["update"],
            invalidates_undo=False,
            local_completion=True,
        )
        self.assertTrue(placement.is_active)
        self.assertEqual(plan_view.cursor_mode, "place")
        # A classified remote UPDATE is the same authoritative Condition row,
        # even though SQL reconstruction supplies another object instance.
        conditions["condition-1"] = Condition(
            uid="condition-1",
            name="Remote rename",
            folder_uid="folder-2",
            layer_uid="layer-2",
            layer_visible=True,
            condition_type=Condition.TYPE_AREA,
        )
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["condition-1"],
            changed_fields=["name"],
            change_operations=["update"],
            invalidates_undo=True,
            local_completion=False,
        )
        self.assertTrue(placement.is_active)
        self.assertEqual(plan_view.cursor_mode, "place")
        # Folder-only hierarchy projection also rebuilds the Condition map but
        # cannot change the active placement contract.
        conditions["condition-1"] = Condition(
            uid="condition-1",
            name="Remote rename",
            folder_uid="folder-3",
            layer_uid="layer-2",
            layer_visible=True,
            condition_type=Condition.TYPE_AREA,
        )
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=[],
            changed_fields=[CollaborationResourceType.CONDITION_FOLDER.value],
            change_operations=[],
            invalidates_undo=True,
            local_completion=False,
        )
        self.assertTrue(placement.is_active)
        self.assertEqual(plan_view.cursor_mode, "place")
        # An unclassified same-UID reconstruction cannot prove that the row is
        # the same incarnation and remains strict.
        conditions["condition-1"] = Condition(
            uid="condition-1",
            name="Unclassified replacement",
            folder_uid="folder-3",
            layer_uid="layer-2",
            layer_visible=True,
            condition_type=Condition.TYPE_AREA,
        )
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["condition-1"],
            changed_fields=[],
            change_operations=[],
            invalidates_undo=True,
            local_completion=False,
        )
        self.assertFalse(placement.is_active)
        self.assertEqual(plan_view.cursor_mode, "select")
        self.assertEqual(plan_view.cancel_calls, 1)
        self.assertTrue(placement.enter("condition-1", ["condition-1"]))
        # A type change is a real placement-contract change and must still exit.
        conditions["condition-1"] = Condition(
            uid="condition-1",
            name="After",
            folder_uid="folder-2",
            layer_uid="layer-2",
            layer_visible=True,
            condition_type=Condition.TYPE_LINEAR,
        )
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["condition-1"],
            changed_fields=["condition_type"],
            change_operations=["update"],
            invalidates_undo=False,
            local_completion=True,
        )
        self.assertFalse(placement.is_active)
        self.assertEqual(plan_view.cursor_mode, "select")
        self.assertEqual(plan_view.cancel_calls, 2)
        # A delayed metadata completion cannot restart placement after a newer
        # authoritative type change invalidated the tool session.
        conditions["condition-1"] = Condition(
            uid="condition-1",
            name="Late local rename",
            folder_uid="folder-2",
            layer_uid="layer-2",
            layer_visible=True,
            condition_type=Condition.TYPE_AREA,
        )
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["condition-1"],
            changed_fields=["name"],
            change_operations=["update"],
            invalidates_undo=False,
            local_completion=True,
        )
        self.assertFalse(placement.is_active)
        self.assertEqual(plan_view.cursor_mode, "select")
        self.assertEqual(plan_view.cancel_calls, 2)

    def test_remote_condition_visibility_change_exits_active_placement(self):
        bid_ref = BidRef("sql-database", "bid-1")
        ui_state = UIStateManager(
            SimpleNamespace(
                display_modes_synced=False,
                display_mode_3d="condition",
                display_mode_2d="condition",
                grayscale_enabled=False,
            )
        )
        ui_state.set_bid_selection(bid_ref)
        ui_state.place_condition_uid = "primary"
        ui_state.set_place_condition_uids(["primary", "secondary"])
        conditions = {
            "primary": Condition(uid="primary", layer_visible=True),
            "secondary": Condition(uid="secondary", layer_visible=False),
        }
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeMainWindow()
        coordinator.ui_state_manager = ui_state
        coordinator.project_data = SimpleNamespace(
            get_bid_conditions=lambda: conditions,
            get_selected_page_uids=lambda: ["page-1"],
        )
        coordinator._undo_service = None
        coordinator._sidebar = SimpleNamespace(
            refresh_conditions_from_memory=lambda: None
        )
        coordinator._restore_sidebar_highlight = lambda _uids, reveal=False: None
        coordinator._update_plan_view_for_active = lambda **_kwargs: None
        coordinator._request_or_defer_mesh_refresh = lambda _pages: None
        coordinator._update_export_menu_state = lambda: None

        class ClearingPlacement(FakePlacement):
            def reconcile_authoritative_conditions(
                self, *, accept_reconstructed_conditions=False
            ):
                _ = accept_reconstructed_conditions
                super().reconcile_authoritative_conditions()
                self.force_exit()
                return False

            def force_exit(self):
                super().force_exit()
                ui_state.clear_place_condition()

        coordinator._placement = ClearingPlacement()
        coordinator._set_plan_select_mode = lambda: None
        coordinator._toolbar = FakeToolbar()
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["secondary"],
            changed_fields=["layer_uid"],
            change_operations=["update"],
        )
        self.assertEqual(coordinator._placement.force_exit_count, 1)
        self.assertIsNone(ui_state.place_condition_uid)

    def test_remote_secondary_condition_retype_exits_active_placement(self):
        bid_ref = BidRef("sql-database", "bid-1")
        ui_state = UIStateManager(
            SimpleNamespace(
                display_modes_synced=False,
                display_mode_3d="condition",
                display_mode_2d="condition",
                grayscale_enabled=False,
            )
        )
        ui_state.set_bid_selection(bid_ref)
        ui_state.place_condition_uid = "primary"
        ui_state.set_place_condition_uids(["primary", "secondary"])
        conditions = {
            "primary": Condition(uid="primary", condition_type=Condition.TYPE_LINEAR),
            "secondary": Condition(uid="secondary", condition_type=Condition.TYPE_AREA),
        }
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeMainWindow()
        coordinator.ui_state_manager = ui_state
        coordinator.project_data = SimpleNamespace(
            get_bid_conditions=lambda: conditions,
            get_selected_page_uids=lambda: ["page-1"],
        )
        coordinator._undo_service = None
        coordinator._sidebar = SimpleNamespace(
            refresh_conditions_from_memory=lambda: None
        )
        coordinator._restore_sidebar_highlight = lambda _uids, reveal=False: None
        coordinator._update_plan_view_for_active = lambda **_kwargs: None
        coordinator._request_or_defer_mesh_refresh = lambda _pages: None
        coordinator._update_export_menu_state = lambda: None

        class ClearingPlacement(FakePlacement):
            def reconcile_authoritative_conditions(
                self, *, accept_reconstructed_conditions=False
            ):
                _ = accept_reconstructed_conditions
                super().reconcile_authoritative_conditions()
                self.force_exit()
                return False

            def force_exit(self):
                super().force_exit()
                ui_state.clear_place_condition()

        coordinator._placement = ClearingPlacement()
        coordinator._set_plan_select_mode = lambda: None
        coordinator._toolbar = FakeToolbar()
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["secondary"],
            changed_fields=["condition_type"],
            change_operations=["update"],
        )
        self.assertEqual(coordinator._placement.force_exit_count, 1)
        self.assertIsNone(ui_state.place_condition_uid)

    def test_remote_condition_folder_move_keeps_valid_active_placement(self):
        bid_ref = BidRef("sql-database", "bid-1")
        ui_state = UIStateManager(
            SimpleNamespace(
                display_modes_synced=False,
                display_mode_3d="condition",
                display_mode_2d="condition",
                grayscale_enabled=False,
            )
        )
        ui_state.set_bid_selection(bid_ref)
        ui_state.place_condition_uid = "primary"
        ui_state.set_place_condition_uids(["primary", "secondary"])
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeMainWindow()
        coordinator.ui_state_manager = ui_state
        coordinator.project_data = SimpleNamespace(
            get_bid_conditions=lambda: {
                "primary": Condition(uid="primary"),
                "secondary": Condition(uid="secondary"),
            },
            get_selected_page_uids=lambda: ["page-1"],
        )
        coordinator._undo_service = None
        coordinator._sidebar = SimpleNamespace(
            refresh_conditions_from_memory=lambda: None
        )
        coordinator._restore_sidebar_highlight = lambda _uids, reveal=False: None
        coordinator._update_plan_view_for_active = lambda **_kwargs: None
        coordinator._request_or_defer_mesh_refresh = lambda _pages: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._placement = FakePlacement()
        coordinator._set_plan_select_mode = lambda: None
        coordinator._toolbar = FakeToolbar()
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["secondary"],
            changed_fields=["folder_uid"],
            change_operations=["update"],
        )
        self.assertEqual(coordinator._placement.force_exit_count, 0)
        self.assertEqual(ui_state.place_condition_uid, "primary")


class UIEventCoordinatorOnRemoteAreasChangedTests(
    _UIEventCoordinatorTakeoffsChangedFixture
):
    """UIEventCoordinator._on_remote_areas_changed."""

    def test_remote_area_change_refreshes_3d_even_without_page_settings_bar(self):
        bid_ref = BidRef("sql-database", "bid-1")
        mesh_refreshes = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.plan_view = None
        coordinator._plan_view_handler = None
        coordinator._pending_takeoff_page_uids = None
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-1",
            get_selected_bid_ref=lambda: bid_ref,
        )
        coordinator.project_data = SimpleNamespace(
            get_selected_page_uids=lambda: ["page-1"]
        )
        coordinator._undo_service = None
        coordinator._page_settings_bar = None
        coordinator._request_or_defer_mesh_refresh = (
            lambda pages: mesh_refreshes.append(list(pages))
        )
        coordinator._tab_widget = None
        coordinator._on_remote_areas_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
        )
        self.assertEqual(mesh_refreshes, [["page-1"]])

    def test_remote_area_refresh_scans_bid_usage_once(self):
        bid_ref = BidRef("sql-database", "bid-1")
        interaction_cancellations = []

        class AreaBar:
            def __init__(self):
                self.current_uid = "deleted-area"

            def get_selected_area_uid(self):
                return self.current_uid

            def load_bid_areas(self, *_args, **_kwargs):
                self.current_uid = ""

        area_bar = AreaBar()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.plan_view = SimpleNamespace(
            has_active_remote_projection_blocker=lambda: True
        )
        coordinator._plan_view_handler = SimpleNamespace(
            prepare_for_authoritative_refresh=lambda: interaction_cancellations.append(
                "cancel"
            )
        )
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-1",
            selected_area_uid="deleted-area",
            get_selected_bid_ref=lambda: bid_ref,
        )
        coordinator.project_data = SimpleNamespace(
            get_bid_area_snapshot=lambda: [],
            get_area_uids_with_takeoff=lambda: set(),
            get_selected_page_uids=lambda: ["page-1"],
        )
        coordinator._undo_service = None
        coordinator._page_settings_bar = area_bar
        scans = []
        coordinator.project_data.get_area_uids_with_takeoff = lambda: scans.append(
            True
        ) or {"new-area"}
        coordinator.project_data.get_area_uids_with_takeoff_for_page = lambda uid: {
            "new-area"
        }
        coordinator.project_data.has_takeoffs_for_pages = lambda uids: True
        coordinator.takeoff_sidebar = FakeTakeoffSidebar()
        usage = []
        area_bar.update_area_usage = lambda bid, page=None: usage.append((bid, page))
        coordinator._request_or_defer_mesh_refresh = lambda _pages: None
        coordinator._tab_widget = None
        coordinator._on_remote_areas_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
        )
        self.assertEqual(coordinator.ui_state_manager.selected_area_uid, "")
        self.assertEqual(interaction_cancellations, ["cancel"])
        self.assertEqual(usage, [({"new-area"}, {"new-area"})])
        self.assertEqual(len(scans), 1)

    def test_remote_area_deletion_clears_canonical_current_area(self):
        bid_ref = BidRef("sql-database", "bid-1")
        interaction_cancellations = []

        class AreaBar:
            def __init__(self):
                self.current_uid = "deleted-area"

            def get_selected_area_uid(self):
                return self.current_uid

            def load_bid_areas(self, *_args, **_kwargs):
                self.current_uid = ""

        area_bar = AreaBar()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.plan_view = SimpleNamespace(
            has_active_remote_projection_blocker=lambda: True
        )
        coordinator._plan_view_handler = SimpleNamespace(
            prepare_for_authoritative_refresh=lambda: interaction_cancellations.append(
                "cancel"
            )
        )
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-1",
            selected_area_uid="deleted-area",
            get_selected_bid_ref=lambda: bid_ref,
        )
        coordinator.project_data = SimpleNamespace(
            get_bid_area_snapshot=lambda: [],
            get_area_uids_with_takeoff=lambda: set(),
            get_selected_page_uids=lambda: ["page-1"],
        )
        coordinator._undo_service = None
        coordinator._page_settings_bar = area_bar
        coordinator._refresh_takeoff_dependent_page_controls = (
            lambda _uid="", **kwargs: None
        )
        coordinator._request_or_defer_mesh_refresh = lambda _pages: None
        coordinator._tab_widget = None
        coordinator._on_remote_areas_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
        )
        self.assertEqual(coordinator.ui_state_manager.selected_area_uid, "")
        self.assertEqual(interaction_cancellations, ["cancel"])

    def test_local_area_completion_preserves_interaction_and_undo_history(self):
        bid_ref = BidRef("sql-database", "bid-1")
        interaction_cancellations = []
        undo_clears = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.plan_view = SimpleNamespace(
            has_active_remote_projection_blocker=lambda: True
        )
        coordinator._plan_view_handler = SimpleNamespace(
            prepare_for_authoritative_refresh=lambda: interaction_cancellations.append(
                "cancel"
            )
        )
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-1",
            selected_area_uid="area-1",
            get_selected_bid_ref=lambda: bid_ref,
        )
        coordinator.project_data = SimpleNamespace(
            get_selected_page_uids=lambda: ["page-1"]
        )
        coordinator._undo_service = SimpleNamespace(
            clear=lambda: undo_clears.append("clear")
        )
        coordinator._page_settings_bar = None
        coordinator._request_or_defer_mesh_refresh = lambda _pages: None
        coordinator._tab_widget = None
        coordinator._on_remote_areas_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            local_completion=True,
        )
        self.assertEqual(interaction_cancellations, [])
        self.assertEqual(undo_clears, [])


class UIEventCoordinatorOnRemoteHierarchyChangedTests(
    _UIEventCoordinatorTakeoffsChangedFixture
):
    """UIEventCoordinator._on_remote_hierarchy_changed."""

    def test_async_restored_sql_bid_runs_canonical_selection_projection(self):
        bid_ref = BidRef("sql-database", "bid-1")

        class ProjectData:
            def __init__(self):
                self.current_file = None
                self.current_bid = None
                self.deselections = 0

            def get_current_bid_ref(self):
                return self.current_bid

            def get_current_file_path(self):
                return self.current_file

            def set_current_file(self, file_path):
                self.current_file = file_path

            def get_bid(self, requested):
                return object() if requested == bid_ref else None

            def deselect_pages(self):
                self.deselections += 1

        project_data = ProjectData()

        class ProjectOperations(ImmediateNavigationOperations):
            def load_bid(self, requested):
                project_data.current_file = requested.file_path
                project_data.current_bid = requested
                return True

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator._status_panel = None
        coordinator.main_window = FakeUnloadMainWindow()
        coordinator.main_window.project_view.selected_node = {
            "kind": "bid",
            "file_path": bid_ref.file_path,
            "bid_uid": bid_ref.bid_uid,
        }
        coordinator.project_data = project_data
        coordinator.project_operations = ProjectOperations()
        coordinator.ui_state_manager = UIStateManager(
            SimpleNamespace(
                display_modes_synced=False,
                display_mode_3d="condition",
                display_mode_2d="condition",
                grayscale_enabled=False,
            )
        )
        coordinator._sql_collaboration = FakeSqlCollaboration()
        coordinator._plan_view_handler = None
        coordinator._placement = FakePlacement()
        coordinator._viewer = FakeUnloadViewer()
        coordinator.visualization_service = FakeVisualization()
        coordinator.ui_access_manager = FakeAccess()
        coordinator._tab_widget = FakeTabWidget(index=0)
        coordinator._nav = FakeNav()
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator._last_mesh_scene = None
        coordinator._pending_3d_takeoff_uids_by_bid = {}
        coordinator._mesh_scene_dirty = False
        coordinator._dirty_mesh_page_uids = set()
        coordinator._pending_dirty_mesh_refresh = False
        coordinator._do_file_refresh = lambda: None
        coordinator._save_current_page_view_state = lambda: None
        coordinator._sync_undo_bid = lambda: None
        coordinator.ensure_select_mode = lambda: None
        coordinator._clear_mesh_views_for_scene_update = lambda **_kwargs: None
        coordinator._resolve_bid_lock_state = lambda _bid_ref: None
        coordinator._reset_takeoff_workspace_state = lambda: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._on_remote_hierarchy_changed(bid_ref.file_path)
        self.assertEqual(coordinator.ui_state_manager.get_selected_bid_ref(), bid_ref)
        self.assertEqual(project_data.current_bid, bid_ref)
        self.assertEqual(project_data.current_file, bid_ref.file_path)
        self.assertEqual(project_data.deselections, 1)
        self.assertEqual(coordinator._tab_widget.visibility, [(1, True), (2, True)])
        self.assertEqual(coordinator.ui_access_manager.refreshes, 1)

    def test_async_sql_only_hierarchy_selects_the_database_root(self):
        database_id = "sql-database"
        project_view = FakeProjectView()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = SimpleNamespace(project_view=project_view)
        coordinator.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: None,
            get_current_file_path=lambda: database_id,
            get_hierarchy=lambda: HierarchyData(
                loaded_files=[HierarchyFileEntry(file_path=database_id)]
            ),
        )
        coordinator.ui_state_manager = SimpleNamespace(
            selected_file_path=None,
            get_selected_bid_ref=lambda: None,
        )
        coordinator._cache_bid_data = lambda _loaded_files: None
        coordinator._sidebar = SimpleNamespace(
            refresh_conditions_from_memory=lambda: None
        )
        coordinator._viewer = SimpleNamespace(update_plan_view_for_active=lambda: None)
        coordinator._on_remote_hierarchy_changed(database_id)
        self.assertEqual(project_view.builds, 1)
        self.assertEqual(
            [loaded.file_path for loaded in project_view.loaded_files],
            [database_id],
        )
        self.assertEqual(project_view.restored_file, database_id)
        self.assertEqual(project_view.selection_notifications, 1)

    def test_remote_project_deletion_projects_tree_fallback_into_ui_state(self):
        database_id = "sql-database"
        project_view = FakeProjectView()
        project_view.selected_node = {
            "kind": "project",
            "file_path": database_id,
            "project_uid": "deleted-project",
        }
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = SimpleNamespace(project_view=project_view)
        coordinator.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: None,
            get_current_file_path=lambda: None,
        )
        ui_state = SimpleNamespace(
            selected_file_path=database_id,
            selected_project_uid="deleted-project",
            get_selected_bid_ref=lambda: None,
        )
        coordinator.ui_state_manager = ui_state

        def project_fallback_selection():
            project_view.selection_notifications += 1
            ui_state.selected_project_uid = None

        project_view.notify_current_selection = project_fallback_selection

        def rebuild_without_deleted_project():
            project_view.selected_node = {
                "kind": "database",
                "file_path": database_id,
                "project_uid": None,
            }

        coordinator._do_file_refresh = rebuild_without_deleted_project
        coordinator._on_remote_hierarchy_changed(database_id)
        self.assertEqual(project_view.selection_notifications, 1)
        self.assertIsNone(ui_state.selected_project_uid)

    def test_delayed_sql_hierarchy_does_not_replace_active_access_bid(self):
        access_bid = BidRef("C:/projects/active.mdb", "bid-1")
        project_view = FakeProjectView()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = SimpleNamespace(project_view=project_view)
        coordinator.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: access_bid,
            get_current_file_path=lambda: access_bid.file_path,
            get_bid=lambda _bid_ref: object(),
        )
        coordinator.ui_state_manager = SimpleNamespace(
            selected_file_path=access_bid.file_path,
            get_selected_bid_ref=lambda: access_bid,
        )
        coordinator._do_file_refresh = lambda: None
        coordinator.handle_bid_selection = lambda *_args, **_kwargs: self.fail(
            "delayed SQL registration must not replace the active Access bid"
        )
        coordinator._on_remote_hierarchy_changed("sql-database")
        self.assertIsNone(project_view.restored_bid)

    def test_remote_hierarchy_refresh_recomputes_active_bid_lock_by_uid(self):
        bid_ref = BidRef("sql-database", "bid-1")
        project_view = FakeProjectView()
        resolved = []
        title_refreshes = []
        condition_refreshes = []
        plan_refreshes = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = SimpleNamespace(
            project_view=project_view,
            refresh_window_title=lambda: title_refreshes.append(True),
        )
        coordinator.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: bid_ref,
            get_current_file_path=lambda: bid_ref.file_path,
            get_bid=lambda requested: object() if requested == bid_ref else None,
        )
        coordinator.ui_state_manager = SimpleNamespace(
            selected_file_path=bid_ref.file_path,
            get_selected_bid_ref=lambda: bid_ref,
        )
        coordinator._sidebar = SimpleNamespace(
            refresh_conditions_from_memory=lambda: condition_refreshes.append(True)
        )
        coordinator._viewer = SimpleNamespace(
            update_plan_view_for_active=lambda: plan_refreshes.append(True)
        )
        coordinator.ui_access_manager = FakeAccess()
        coordinator._update_menu_state = lambda: None
        coordinator._do_file_refresh = lambda: None
        coordinator._resolve_bid_lock_state = resolved.append
        coordinator._on_remote_hierarchy_changed(bid_ref.file_path)
        self.assertEqual(resolved, [bid_ref])
        self.assertEqual(coordinator.ui_access_manager.refreshes, 1)
        self.assertEqual(project_view.restored_bid, bid_ref)
        self.assertEqual(title_refreshes, [True])
        self.assertEqual(condition_refreshes, [True])
        self.assertEqual(plan_refreshes, [])
        condition_refreshes.clear()
        coordinator._on_remote_hierarchy_changed(
            bid_ref.file_path,
            condition_family_projected=True,
        )
        self.assertEqual(condition_refreshes, [])


class UIEventCoordinatorOnRemoteBidContentChangedTests(
    _UIEventCoordinatorTakeoffsChangedFixture
):
    """UIEventCoordinator._on_remote_bid_content_changed."""

    def test_deferred_page_metadata_refreshes_summary_and_status_without_plan(self):
        bid_ref = BidRef("sql-database", "bid-1")
        page = Page(uid="page-1", name="Renamed Sheet", sequence=1)
        summary_refreshes = []
        page_settings = []
        status = _CollaborationStatusPanel()
        status.set_page_info("Old Sheet")

        class UiState:
            active_page_uid = page.uid
            selected_page_uids = [page.uid]

            @staticmethod
            def get_selected_bid_ref():
                return bid_ref

            def set_page_selection(self, page_uids):
                self.selected_page_uids = list(page_uids)

        class ProjectData:
            @staticmethod
            def get_page(page_uid):
                return page if page_uid == page.uid else None

            @staticmethod
            def get_all_pages():
                return [page]

            @staticmethod
            def select_pages(page_uids):
                return list(page_uids)

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = UiState()
        coordinator.project_data = ProjectData()
        coordinator.project_operations = ImmediateNavigationOperations()
        coordinator._status_panel = status
        coordinator._tab_widget = FakeTabWidget(index=TAB_INDEX_SUMMARY)
        coordinator._view_stack = FakeViewStack(index=1)
        coordinator._pending_takeoff_page_uids = None
        coordinator._undo_service = None
        coordinator._selected_takeoff_uids = ()
        coordinator._plan_view_handler = None
        coordinator.plan_view = None
        coordinator._deferred_persistence = SimpleNamespace(
            reproject_newer_page_visual_revisions=lambda *_args: None
        )
        coordinator._sidebar = SimpleNamespace(
            bid_layers_sidebar=None,
            load_takeoff_sidebar_from_memory=lambda *_args: None,
        )
        coordinator._bid_data_cache = {}
        coordinator.main_window = FakeMainWindow()
        coordinator.takeoff_sidebar = SimpleNamespace(
            restore_selection=lambda *_args: False
        )
        coordinator._page_settings_bar = object()
        coordinator._update_page_settings_bar = page_settings.append
        coordinator._sync_overlay_display_mode = lambda _page_uid: None
        coordinator._sync_navigation_for_active_page = lambda *_args: None
        coordinator._load_condition_summary = lambda: summary_refreshes.append(True)
        coordinator._update_export_menu_state = lambda: None
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        coordinator._on_remote_bid_content_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            families=[CollaborationResourceFamily.PAGES.value],
            resource_uids_by_family={
                CollaborationResourceFamily.PAGES.value: [page.uid]
            },
            affected_page_uids_by_family={
                CollaborationResourceFamily.PAGES.value: [page.uid]
            },
            defer_plan_projection=True,
            local_completion=True,
        )
        self.assertEqual(page_settings, [page.uid])
        self.assertEqual(summary_refreshes, [True])
        self.assertEqual(status.page_info, page.name)
        self.assertEqual(
            coordinator.main_window.project_view.bid_content_counts,
            [(bid_ref, {"page_count": 1})],
        )
        coordinator._on_remote_bid_content_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            families=[CollaborationResourceFamily.PAGES.value],
            resource_uids_by_family={
                CollaborationResourceFamily.PAGES.value: [page.uid]
            },
            affected_page_uids_by_family={
                CollaborationResourceFamily.PAGES.value: [page.uid]
            },
            defer_plan_projection=True,
            local_completion=True,
            area_family_projected=True,
        )
        self.assertEqual(summary_refreshes, [True])

    def test_remote_transaction_defers_to_one_plan_projection(self):
        database_id = "sql-db"
        bid_uid = "bid-1"

        class SelectedUiState(FakeUiState):
            def get_selected_bid_ref(self):
                return BidRef(database_id, bid_uid)

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SelectedUiState()
        coordinator.project_data = FakeProjectData()
        coordinator.takeoff_sidebar = FakeTakeoffSidebar()
        coordinator._page_settings_bar = FakePageSettingsBar()
        coordinator._viewer = FakeViewer()
        coordinator._sidebar = FakeSidebar()
        coordinator._toolbar = FakeToolbar()
        coordinator.main_window = FakeMainWindow()
        coordinator.plan_view = SimpleNamespace(
            has_active_remote_projection_blocker=lambda: False
        )
        coordinator._plan_view_handler = None
        coordinator._is_cleaning_up = False
        coordinator._undo_service = None
        coordinator._selected_takeoff_uids = ()
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        configure_mesh_state(coordinator, view_index=0)
        completed = []
        barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=3,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=completed.append,
        )
        coordinator._on_remote_bid_content_changed(
            database_id=database_id,
            bid_uid=bid_uid,
            families=[CollaborationResourceFamily.TAKEOFFS.value],
            resource_uids_by_family={
                CollaborationResourceFamily.TAKEOFFS.value: ["takeoff-1"]
            },
            defer_plan_projection=True,
        )
        self.assertEqual(coordinator._viewer.plan_pages, [])
        self.assertEqual(coordinator.visualization_service.mesh_pages, [])
        coordinator._on_remote_plan_projection_requested(
            database_id=database_id,
            bid_uid=bid_uid,
            runtime_generation=3,
            families=(CollaborationResourceFamily.TAKEOFFS.value,),
            condition_uids=(),
            condition_changed_fields=None,
            condition_change_operations=(),
            areas_changed=False,
            resource_uids_by_family={
                CollaborationResourceFamily.TAKEOFFS.value: ("takeoff-1",)
            },
            barrier=barrier,
        )
        barrier.seal()
        self.assertEqual(len(coordinator._viewer.remote_requests), 1)
        self.assertEqual(coordinator.visualization_service.mesh_pages, [["page-1"]])
        self.assertEqual(completed, [True])
        self.assertEqual(coordinator._sidebar.quantity_updates, 1)
        coordinator.plan_view = None
        coordinator.visualization_service.mesh_pages.clear()
        metadata_barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=4,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        coordinator._on_remote_plan_projection_requested(
            database_id=database_id,
            bid_uid=bid_uid,
            runtime_generation=4,
            families=(),
            condition_uids=("condition-1",),
            condition_changed_fields=("name",),
            condition_change_operations=("update",),
            areas_changed=False,
            resource_uids_by_family={},
            barrier=metadata_barrier,
        )
        self.assertEqual(coordinator.visualization_service.mesh_pages, [])
        coordinator._on_remote_plan_projection_requested(
            database_id=database_id,
            bid_uid=bid_uid,
            runtime_generation=4,
            families=(),
            condition_uids=("condition-1",),
            condition_changed_fields=("z_value",),
            condition_change_operations=("update",),
            areas_changed=False,
            resource_uids_by_family={},
            barrier=metadata_barrier,
        )
        self.assertEqual(coordinator.visualization_service.mesh_pages, [["page-1"]])

    def test_remote_annotation_on_other_page_does_not_cancel_main_interaction(self):
        bid_ref = BidRef("sql-db", "bid-1")
        cancellations = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-1",
            get_selected_bid_ref=lambda: bid_ref,
        )
        coordinator.plan_view = SimpleNamespace(
            has_active_remote_projection_blocker=lambda: True
        )
        coordinator._plan_view_handler = SimpleNamespace(
            prepare_for_authoritative_refresh=lambda: cancellations.append(True)
        )
        coordinator._undo_service = None
        coordinator._selected_takeoff_uids = ()
        coordinator._update_export_menu_state = lambda: None
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        coordinator._on_remote_bid_content_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            families=(CollaborationResourceFamily.ANNOTATIONS.value,),
            resource_uids_by_family={
                CollaborationResourceFamily.ANNOTATIONS.value: ("text/annotation-1",)
            },
            affected_page_uids_by_family={
                CollaborationResourceFamily.ANNOTATIONS.value: ("page-2",)
            },
            defer_plan_projection=True,
        )
        self.assertEqual(cancellations, [])

    def test_remote_takeoff_deletion_reconciles_canonical_cross_view_selection(self):
        bid_ref = BidRef("sql-db", "bid-1")
        ui_state = UIStateManager(
            SimpleNamespace(
                display_modes_synced=False,
                display_mode_3d="condition",
                display_mode_2d="condition",
                grayscale_enabled=False,
            )
        )
        ui_state.set_bid_selection(bid_ref)
        ui_state.active_page_uid = "page-1"
        ui_state.set_page_selection(["page-1"])
        ui_state.set_highlighted_conditions({"condition-1"})
        sidebar_highlights = []
        conditions_sidebar = SimpleNamespace(
            get_selected_condition_uids=lambda: ["condition-1"],
            highlight_conditions=lambda uids, reveal=True: sidebar_highlights.append(
                (set(uids), reveal)
            ),
        )

        class SelectionSurface:
            def __init__(self):
                self.selections = []

            def set_selected_takeoffs(self, uids):
                self.selections.append(list(uids))

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = ui_state
        coordinator.project_data = SimpleNamespace(
            get_all_takeoffs=lambda: [],
            get_bid_conditions=lambda: {"condition-1": object()},
            get_selected_page_uids=lambda: ["page-1"],
        )
        coordinator._selected_takeoff_uids = ("deleted-takeoff",)
        coordinator._selection_projected_condition_uids = {"condition-1"}
        coordinator._placement = FakePlacement()
        coordinator._toolbar = FakeToolbar()
        coordinator._nav = FakeNav()
        coordinator.conditions_sidebar = conditions_sidebar
        coordinator.plan_view = None
        coordinator.opengl_viewer = SelectionSurface()
        coordinator._mesh_window = SelectionSurface()
        coordinator._tab_widget = None
        coordinator._undo_service = None
        coordinator._refresh_takeoff_dependent_page_controls = (
            lambda _uid="", **kwargs: None
        )
        coordinator._is_summary_tab_active = lambda: False
        coordinator._sidebar = SimpleNamespace(
            update_conditions_quantities=lambda **_kwargs: None,
            bid_layers_sidebar=None,
        )
        coordinator._update_export_menu_state = lambda: None
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        coordinator._on_remote_bid_content_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            families=[CollaborationResourceFamily.TAKEOFFS.value],
            resource_uids_by_family={
                CollaborationResourceFamily.TAKEOFFS.value: ["deleted-takeoff"]
            },
            defer_plan_projection=True,
        )
        self.assertEqual(coordinator._selected_takeoff_uids, ())
        self.assertEqual(ui_state.highlighted_condition_uids, set())
        self.assertEqual(sidebar_highlights, [(set(), True)])
        self.assertEqual(coordinator.opengl_viewer.selections, [[]])
        self.assertEqual(coordinator._mesh_window.selections, [[]])

    def test_remote_partial_takeoff_deletion_preserves_only_surviving_selection(self):
        bid_ref = BidRef("sql-db", "bid-1")
        ui_state = UIStateManager(
            SimpleNamespace(
                display_modes_synced=False,
                display_mode_3d="condition",
                display_mode_2d="condition",
                grayscale_enabled=False,
            )
        )
        ui_state.set_bid_selection(bid_ref)
        ui_state.active_page_uid = "page-1"
        ui_state.set_page_selection(["page-1"])
        ui_state.set_highlighted_conditions({"condition-1"})

        class SelectionSurface:
            def __init__(self):
                self.selections = []

            def set_selected_takeoffs(self, uids):
                self.selections.append(list(uids))

        survivor = Takeoff(
            uid="survivor",
            condition_uid="condition-1",
            page_uid="page-1",
        )
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = ui_state
        coordinator.project_data = SimpleNamespace(
            get_all_takeoffs=lambda: [survivor],
            get_bid_conditions=lambda: {"condition-1": object()},
            get_selected_page_uids=lambda: ["page-1"],
        )
        coordinator._selected_takeoff_uids = ("deleted", "survivor")
        coordinator._selection_projected_condition_uids = {"condition-1"}
        coordinator._placement = FakePlacement()
        coordinator._nav = FakeNav()
        coordinator.conditions_sidebar = SimpleNamespace(
            get_selected_condition_uids=lambda: ["condition-1"]
        )
        interaction_sequence = []
        coordinator.plan_view = SimpleNamespace(
            has_active_remote_projection_blocker=lambda: True,
            set_selected_uids=lambda uids, emit=False: interaction_sequence.append(
                ("selection", set(uids), emit)
            ),
        )
        coordinator._plan_view_handler = SimpleNamespace(
            prepare_for_authoritative_refresh=lambda: interaction_sequence.append(
                "cancel"
            )
        )
        coordinator.opengl_viewer = SelectionSurface()
        coordinator._mesh_window = SelectionSurface()
        coordinator._tab_widget = None
        coordinator._undo_service = None
        coordinator._refresh_takeoff_dependent_page_controls = (
            lambda _uid="", **kwargs: None
        )
        coordinator._is_summary_tab_active = lambda: False
        coordinator._sidebar = SimpleNamespace(
            update_conditions_quantities=lambda **_kwargs: None,
            bid_layers_sidebar=None,
        )
        coordinator._update_export_menu_state = lambda: None
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        coordinator._on_remote_bid_content_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            families=[CollaborationResourceFamily.TAKEOFFS.value],
            resource_uids_by_family={
                CollaborationResourceFamily.TAKEOFFS.value: ["deleted"]
            },
            defer_plan_projection=True,
        )
        self.assertEqual(coordinator._selected_takeoff_uids, ("survivor",))
        self.assertEqual(ui_state.highlighted_condition_uids, {"condition-1"})
        self.assertEqual(coordinator.opengl_viewer.selections, [["survivor"]])
        self.assertEqual(coordinator._mesh_window.selections, [["survivor"]])
        self.assertEqual(
            interaction_sequence,
            ["cancel", ("selection", {"survivor"}, False)],
        )

    def test_remote_layer_reconciliation_derives_takeoff_layer_from_condition(self):
        database_id = "sql-db"
        bid_uid = "bid-1"

        class SelectedUiState(FakeUiState):
            def get_selected_bid_ref(self):
                return BidRef(database_id, bid_uid)

        loaded = []
        layer_sidebar = SimpleNamespace(
            load_layers=lambda layers, used_uids: loaded.append(
                (list(layers), set(used_uids))
            )
        )
        sidebar = SimpleNamespace(
            bid_layers_sidebar=layer_sidebar,
            refresh_conditions_from_memory=lambda: None,
        )
        takeoff = Takeoff(uid="4485", condition_uid="10", page_uid="20")
        model = SimpleNamespace(
            bid_layers=[
                BidLayer(
                    uid="25",
                    bid_uid=bid_uid,
                    name="Takeoff layer",
                    show=True,
                    sequence=0,
                )
            ],
            bid_layer_visibility={"25": True},
            bid_layer_names_by_uid={"25": "Takeoff layer"},
            current_bid_ref=BidRef(database_id, bid_uid),
            bid_conditions={"10": Condition(uid="10", layer_uid="25")},
            get_selected_pages=lambda: [],
            get_all_takeoffs=lambda: [takeoff],
            get_all_annotations=lambda: [],
        )
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.plan_view = None
        coordinator._plan_view_handler = None
        coordinator.ui_state_manager = SelectedUiState()
        coordinator.project_data = ProjectDataService(model)
        coordinator._deferred_persistence = SimpleNamespace(
            invalidate_layer_visual_revisions=lambda *_args: None
        )
        coordinator._placement = FakePlacement()
        coordinator._undo_service = None
        coordinator._sidebar = sidebar
        mesh_refreshes = []
        coordinator._request_or_defer_mesh_refresh = (
            lambda pages: mesh_refreshes.append(list(pages))
        )
        coordinator._update_plan_view_for_active = lambda **kwargs: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        coordinator._on_remote_bid_content_changed(
            database_id=database_id,
            bid_uid=bid_uid,
            families=[CollaborationResourceFamily.LAYERS.value],
            defer_plan_projection=False,
        )
        self.assertEqual(len(loaded), 1)
        self.assertEqual([layer.uid for layer in loaded[0][0]], ["25"])
        self.assertEqual(loaded[0][1], {"25"})
        self.assertEqual(mesh_refreshes, [[]])
        self.assertEqual(coordinator._placement.reconciliation_calls, 1)
        mesh_refreshes.clear()
        coordinator._on_remote_bid_content_changed(
            database_id=database_id,
            bid_uid=bid_uid,
            families=["layers"],
            mesh_scene_unchanged=True,
            image_sources_unchanged=True,
        )
        self.assertEqual(mesh_refreshes, [])
        self.assertEqual(len(loaded), 2)

    def test_combined_remote_annotation_and_layer_update_projects_main_once(self):
        bid_ref = BidRef("sql-db", "bid-1")
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.plan_view = None
        coordinator._plan_view_handler = None
        coordinator.ui_state_manager = FakeUiState(bid_ref)
        coordinator._placement = FakePlacement()
        coordinator.project_data = SimpleNamespace(
            get_bid_layer_snapshot=lambda: [],
            get_layer_uids_in_use=lambda: set(),
            get_selected_page_uids=lambda: ["page-1"],
        )
        coordinator._deferred_persistence = SimpleNamespace(
            invalidate_layer_visual_revisions=lambda *_args: None
        )
        coordinator._undo_service = None
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        coordinator._viewer = FakeViewer()
        coordinator._sidebar = SimpleNamespace(
            bid_layers_sidebar=SimpleNamespace(
                load_layers=lambda *_args, **_kwargs: None
            ),
            refresh_conditions_from_memory=lambda: None,
            update_conditions_quantities=lambda **_kwargs: None,
        )
        coordinator._request_or_defer_mesh_refresh = lambda _pages: None
        coordinator._apply_pending_hotlink_named_view_focus = lambda **_kwargs: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        coordinator._on_remote_bid_content_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            families=[
                CollaborationResourceFamily.ANNOTATIONS.value,
                CollaborationResourceFamily.LAYERS.value,
            ],
        )
        self.assertEqual(coordinator._viewer.plan_pages, ["active"])

    def test_local_annotation_completion_preserves_type_scoped_identities(self):
        bid_ref = BidRef("sql-db", "bid-1")
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.plan_view = None
        coordinator._plan_view_handler = None
        coordinator.ui_state_manager = FakeUiState(bid_ref)
        coordinator._placement = FakePlacement()
        coordinator.project_data = SimpleNamespace()
        coordinator._undo_service = None
        coordinator._selected_takeoff_uids = ()
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        coordinator._viewer = FakeViewer()
        coordinator._sidebar = SimpleNamespace()
        coordinator._update_export_menu_state = lambda: None
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        coordinator._on_remote_bid_content_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            families=[CollaborationResourceFamily.ANNOTATIONS.value],
            resource_uids_by_family={
                CollaborationResourceFamily.ANNOTATIONS.value: [
                    "rect/shared",
                    "oval/shared",
                ]
            },
            local_completion=True,
        )
        self.assertEqual(
            coordinator._viewer.changed_annotation_uids, [["shared", "shared"]]
        )
        self.assertEqual(
            coordinator._viewer.changed_annotation_types, [["rect", "oval"]]
        )

    def test_local_layer_completion_preserves_newer_visual_revision(self):
        bid_ref = BidRef("sql-db", "bid-1")
        invalidated = []
        reprojected = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = FakeUiState(bid_ref)
        coordinator._placement = FakePlacement()
        coordinator.project_data = SimpleNamespace(
            get_selected_page_uids=lambda: ["page-1"]
        )
        coordinator._deferred_persistence = SimpleNamespace(
            invalidate_layer_visual_revisions=lambda *args: invalidated.append(args),
            reproject_newer_layer_visual_revisions=lambda *args: reprojected.append(
                args
            ),
        )
        coordinator._undo_service = None
        coordinator._viewer = FakeViewer()
        coordinator._sidebar = SimpleNamespace(
            bid_layers_sidebar=None,
            update_conditions_quantities=lambda **_kwargs: None,
        )
        coordinator._request_or_defer_mesh_refresh = lambda _pages: None
        coordinator._apply_pending_hotlink_named_view_focus = lambda **_kwargs: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        coordinator._on_remote_bid_content_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            families=[CollaborationResourceFamily.LAYERS.value],
            local_completion=True,
        )
        self.assertEqual(coordinator._viewer.plan_pages, ["active"])
        self.assertEqual(invalidated, [])
        self.assertEqual(reprojected, [("sql-db", None)])

    def test_remote_layer_reconciliation_exits_hidden_condition_placement(self):
        bid_ref = BidRef("sql-db", "bid-1")
        ui_state = UIStateManager(
            SimpleNamespace(
                display_modes_synced=False,
                display_mode_3d="condition",
                display_mode_2d="condition",
                grayscale_enabled=False,
            )
        )
        ui_state.set_bid_selection(bid_ref)
        ui_state.place_condition_uid = "condition-1"
        ui_state.set_place_condition_uids(["condition-1"])
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.plan_view = None
        coordinator._plan_view_handler = None
        coordinator.ui_state_manager = ui_state
        coordinator.project_data = SimpleNamespace(
            get_bid_conditions=lambda: {
                "condition-1": Condition(
                    uid="condition-1", layer_uid="layer-1", layer_visible=False
                )
            },
            get_selected_page_uids=lambda: ["page-1"],
        )
        coordinator._deferred_persistence = SimpleNamespace(
            invalidate_layer_visual_revisions=lambda *_args: None
        )
        coordinator._undo_service = None
        coordinator._viewer = FakeViewer()
        coordinator._sidebar = SimpleNamespace(
            bid_layers_sidebar=None,
            update_conditions_quantities=lambda **_kwargs: None,
        )
        coordinator._update_plan_view_for_active = lambda **kwargs: None
        coordinator._request_or_defer_mesh_refresh = lambda _pages: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None

        class ClearingPlacement(FakePlacement):
            def reconcile_authoritative_conditions(
                self, *, accept_reconstructed_conditions=False
            ):
                _ = accept_reconstructed_conditions
                super().reconcile_authoritative_conditions()
                self.force_exit()
                return False

            def force_exit(self):
                super().force_exit()
                ui_state.clear_place_condition()

        coordinator._placement = ClearingPlacement()
        coordinator._set_plan_select_mode = lambda: None
        coordinator._toolbar = FakeToolbar()
        coordinator._on_remote_bid_content_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            families=[CollaborationResourceFamily.LAYERS.value],
        )
        self.assertEqual(coordinator._placement.force_exit_count, 1)
        self.assertIsNone(ui_state.place_condition_uid)

    def test_combined_remote_page_and_annotation_update_projects_main_once(self):
        bid_ref = BidRef("sql-db", "bid-1")
        page = Page(uid="page-1", name="Page 1", sequence=1)
        cancelled_pages = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeMainWindow()
        coordinator._tab_widget = None
        coordinator._status_panel = None
        coordinator.plan_view = None
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator._plan_view_handler = None
        coordinator._pending_takeoff_page_uids = None
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-1",
            selected_page_uids=["page-1"],
            get_selected_bid_ref=lambda: bid_ref,
            set_page_selection=lambda _pages: None,
        )
        coordinator.project_data = SimpleNamespace(
            get_page=lambda uid: page if uid == "page-1" else None,
            get_all_pages=lambda: [page],
            select_pages=lambda pages: list(pages),
        )
        coordinator._deferred_persistence = SimpleNamespace(
            invalidate_page_visual_revisions=lambda *_args: None,
            cancel_pages=lambda database_id, bid_uid, page_uids: cancelled_pages.append(
                (database_id, bid_uid, page_uids)
            ),
        )
        coordinator._undo_service = None
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        coordinator._viewer = FakeViewer()
        coordinator._sidebar = SimpleNamespace(
            bid_layers_sidebar=None,
            load_takeoff_sidebar_from_memory=lambda *_args: None,
            update_conditions_quantities=lambda **_kwargs: None,
        )
        coordinator._bid_data_cache = {}
        coordinator.takeoff_sidebar = SimpleNamespace(
            restore_selection=lambda _pages, _active: None
        )
        coordinator._update_page_settings_bar = lambda _page_uid: None
        coordinator._request_or_defer_mesh_refresh = lambda _pages: None
        coordinator._apply_pending_hotlink_named_view_focus = lambda **_kwargs: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        coordinator._on_remote_bid_content_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            families=[
                CollaborationResourceFamily.ANNOTATIONS.value,
                CollaborationResourceFamily.PAGES.value,
            ],
        )
        self.assertEqual(coordinator._viewer.plan_pages, ["page-1"])
        self.assertEqual(cancelled_pages, [("sql-db", "bid-1", None)])

    def test_combined_remote_page_and_takeoff_update_projects_derived_state_once(self):
        bid_ref = BidRef("sql-db", "bid-1")
        page = Page(uid="page-1", name="Page 1", sequence=1)
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeMainWindow()
        coordinator._status_panel = None
        coordinator.plan_view = SimpleNamespace(
            has_active_remote_projection_blocker=lambda: False
        )
        coordinator._plan_view_handler = None
        coordinator._pending_takeoff_page_uids = None
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid=page.uid,
            selected_page_uids=[page.uid],
            get_selected_bid_ref=lambda: bid_ref,
            set_page_selection=lambda _pages: None,
        )
        coordinator.project_data = SimpleNamespace(
            get_page=lambda uid: page if uid == page.uid else None,
            get_all_pages=lambda: [page],
            get_selected_page_uids=lambda: [page.uid],
            select_pages=lambda pages: list(pages),
            has_takeoffs_for_pages=lambda _pages: True,
            get_area_uids_with_takeoff=lambda: set(),
        )
        coordinator._deferred_persistence = SimpleNamespace(
            invalidate_page_visual_revisions=lambda *_args: None,
            cancel_pages=lambda *_args: None,
        )
        coordinator._undo_service = None
        coordinator._selected_takeoff_uids = ()
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        coordinator._viewer = FakeViewer()
        quantity_refreshes = []
        summary_refreshes = []
        coordinator._sidebar = SimpleNamespace(
            bid_layers_sidebar=None,
            load_takeoff_sidebar_from_memory=lambda *_args: None,
            update_conditions_quantities=lambda **_kwargs: quantity_refreshes.append(
                coordinator.ui_state_manager.active_page_uid
            ),
        )
        coordinator._bid_data_cache = {}
        coordinator.takeoff_sidebar = SimpleNamespace(
            set_page_has_takeoffs=lambda *_args: None,
            restore_selection=lambda *_args: None,
        )
        coordinator._page_settings_bar = None
        coordinator._update_page_settings_bar = lambda _page_uid: None
        coordinator._sync_overlay_display_mode = lambda _page_uid: None
        coordinator._apply_pending_hotlink_named_view_focus = lambda **_kwargs: None
        mesh_refreshes = []
        coordinator._request_or_defer_mesh_refresh = (
            lambda pages, **_kwargs: mesh_refreshes.append(list(pages))
        )
        coordinator._is_summary_tab_active = lambda: True
        coordinator._load_condition_summary = lambda: summary_refreshes.append(True)
        coordinator._update_export_menu_state = lambda: None
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        coordinator._on_remote_bid_content_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            families=[
                CollaborationResourceFamily.PAGES.value,
                CollaborationResourceFamily.TAKEOFFS.value,
            ],
            affected_page_uids_by_family={
                CollaborationResourceFamily.TAKEOFFS.value: [page.uid]
            },
        )
        self.assertEqual(coordinator._viewer.plan_pages, [page.uid])
        self.assertEqual(mesh_refreshes, [[page.uid]])
        self.assertEqual(quantity_refreshes, [page.uid])
        self.assertEqual(summary_refreshes, [True])

    def test_deferred_page_takeoff_batch_refreshes_counts_after_page_fallback(self):
        bid_ref = BidRef("sql-db", "bid-1")
        remaining = Page(uid="page-b", name="Page B", sequence=2)
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeMainWindow()
        coordinator._status_panel = None
        coordinator.plan_view = SimpleNamespace(
            has_active_remote_projection_blocker=lambda: False
        )
        coordinator._plan_view_handler = None
        coordinator._pending_takeoff_page_uids = None
        ui_state = SimpleNamespace(
            active_page_uid="deleted-page",
            selected_page_uids=["deleted-page"],
            get_selected_bid_ref=lambda: bid_ref,
        )

        def set_page_selection(page_uids):
            ui_state.selected_page_uids = list(page_uids)

        ui_state.set_page_selection = set_page_selection
        coordinator.ui_state_manager = ui_state
        coordinator.project_data = SimpleNamespace(
            get_page=lambda uid: remaining if uid == remaining.uid else None,
            get_all_pages=lambda: [remaining],
            get_selected_page_uids=lambda: [remaining.uid],
            select_pages=lambda pages: list(pages),
            has_takeoffs_for_pages=lambda _pages: True,
            get_area_uids_with_takeoff=lambda: set(),
        )
        coordinator._deferred_persistence = SimpleNamespace(
            invalidate_page_visual_revisions=lambda *_args: None,
            cancel_pages=lambda *_args: None,
        )
        coordinator._undo_service = None
        coordinator._selected_takeoff_uids = ()
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        coordinator._viewer = FakeViewer()
        quantity_pages = []
        summary_refreshes = []
        coordinator._sidebar = SimpleNamespace(
            bid_layers_sidebar=None,
            load_takeoff_sidebar_from_memory=lambda *_args: None,
            update_conditions_quantities=lambda **_kwargs: quantity_pages.append(
                ui_state.active_page_uid
            ),
        )
        coordinator._bid_data_cache = {}
        coordinator.takeoff_sidebar = SimpleNamespace(
            set_page_has_takeoffs=lambda *_args: None,
            restore_selection=lambda *_args: None,
        )
        coordinator._page_settings_bar = None
        coordinator._update_page_settings_bar = lambda _page_uid: None
        coordinator._sync_overlay_display_mode = lambda _page_uid: None
        coordinator._sync_navigation_for_active_page = lambda *_args: None
        coordinator._request_or_defer_mesh_refresh = lambda *_args, **_kwargs: None
        coordinator._is_summary_tab_active = lambda: True
        coordinator._load_condition_summary = lambda: summary_refreshes.append(True)
        coordinator._update_export_menu_state = lambda: None
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        coordinator._on_remote_bid_content_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            families=[
                CollaborationResourceFamily.PAGES.value,
                CollaborationResourceFamily.TAKEOFFS.value,
            ],
            affected_page_uids_by_family={
                CollaborationResourceFamily.TAKEOFFS.value: [remaining.uid]
            },
            defer_plan_projection=True,
        )
        self.assertEqual(ui_state.active_page_uid, remaining.uid)
        self.assertEqual(quantity_pages, [remaining.uid])
        self.assertEqual(summary_refreshes, [True])
        self.assertEqual(coordinator._viewer.plan_pages, [])

    def test_remote_page_scene_impact_controls_immediate_and_deferred_generation(self):
        bid_ref = BidRef("sql-db", "bid-1")
        page = Page(uid="page-1", name="Page 1", sequence=1)
        cancelled_pages = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeMainWindow()
        coordinator._tab_widget = None
        coordinator._status_panel = None
        coordinator.plan_view = None
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator._plan_view_handler = None
        coordinator._pending_takeoff_page_uids = None
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-1",
            selected_page_uids=["page-1"],
            get_selected_bid_ref=lambda: bid_ref,
            set_page_selection=lambda _pages: None,
        )
        coordinator.project_data = SimpleNamespace(
            get_page=lambda uid: page if uid == "page-1" else None,
            get_all_pages=lambda: [page],
            select_pages=lambda pages: list(pages),
        )
        coordinator._deferred_persistence = SimpleNamespace(
            invalidate_page_visual_revisions=lambda *_args: None,
            cancel_pages=lambda database_id, bid_uid, page_uids: cancelled_pages.append(
                (database_id, bid_uid, page_uids)
            ),
        )
        coordinator._undo_service = None
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        coordinator._viewer = FakeViewer()
        coordinator._sidebar = SimpleNamespace(
            bid_layers_sidebar=None,
            load_takeoff_sidebar_from_memory=lambda *_args: None,
            update_conditions_quantities=lambda **_kwargs: None,
        )
        coordinator._bid_data_cache = {}
        coordinator.takeoff_sidebar = SimpleNamespace(
            restore_selection=lambda _pages, _active: None
        )
        coordinator._update_page_settings_bar = lambda _page_uid: None
        coordinator._request_or_defer_mesh_refresh = lambda _pages: None
        coordinator._apply_pending_hotlink_named_view_focus = lambda **_kwargs: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        mesh_calls = []
        coordinator._request_or_defer_mesh_refresh = lambda pages: mesh_calls.append(
            list(pages)
        )
        coordinator.project_data.get_selected_page_uids = lambda: ["page-1"]
        coordinator._is_cleaning_up = False
        texture_calls = []
        coordinator._update_native_page_textures = lambda: texture_calls.append(True)
        for unchanged, texture_only in ((True, False), (False, False), (False, True)):
            with self.subTest(unchanged=unchanged):
                mesh_calls.clear()
                texture_calls.clear()
                coordinator._on_remote_bid_content_changed(
                    database_id=bid_ref.file_path,
                    bid_uid=bid_ref.bid_uid,
                    families=["pages"],
                    mesh_scene_unchanged=unchanged,
                    page_texture_only=texture_only,
                )
                self.assertEqual(
                    mesh_calls, [] if unchanged or texture_only else [["page-1"]]
                )
                self.assertEqual(len(texture_calls), int(texture_only))
                self.assertEqual(coordinator._viewer.plan_pages[-1], "page-1")
                mesh_calls.clear()
                texture_calls.clear()
                barrier = RemoteProjectionBarrier(
                    database_id=bid_ref.file_path,
                    runtime_generation=1,
                    is_runtime_current=lambda *_args: True,
                    on_complete=lambda _ok: None,
                )
                coordinator._on_remote_plan_projection_requested(
                    database_id=bid_ref.file_path,
                    bid_uid=bid_ref.bid_uid,
                    runtime_generation=1,
                    families=("pages",),
                    condition_uids=(),
                    condition_changed_fields=None,
                    condition_change_operations=(),
                    areas_changed=False,
                    resource_uids_by_family={"pages": ("page-1",)},
                    barrier=barrier,
                    mesh_scene_unchanged=unchanged,
                    page_texture_only=texture_only,
                )
                self.assertEqual(
                    mesh_calls, [] if unchanged or texture_only else [["page-1"]]
                )
                self.assertEqual(len(texture_calls), int(texture_only))

    def test_remote_page_removal_republishes_scene_for_remaining_checked_pages(self):
        bid_ref = BidRef("sql-db", "bid-1")
        remaining_page = Page(uid="page-a", name="Page A", sequence=1)
        selected_pages = []
        mesh_refreshes = []
        terminal_clears = []
        restored_navigation = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeMainWindow()
        coordinator._tab_widget = None
        coordinator._status_panel = None
        coordinator.plan_view = None
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator._plan_view_handler = None
        coordinator._pending_takeoff_page_uids = None
        coordinator._nav = NavigationStateMachine()
        coordinator._nav.transition_to(NavState.FILE_LOADED_NO_BID)
        coordinator._nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)
        coordinator._nav.transition_to(NavState.BID_ACTIVE_PAGES_SELECTED)
        coordinator.ui_state_manager = SimpleNamespace(
            selected_page_uids=["page-a", "deleted-page"],
            active_page_uid="deleted-page",
            get_selected_bid_ref=lambda: bid_ref,
            set_page_selection=lambda pages: selected_pages.append(list(pages)),
        )
        coordinator.project_data = SimpleNamespace(
            get_page=lambda uid: remaining_page if uid == "page-a" else None,
            get_all_pages=lambda: [remaining_page],
            select_pages=lambda pages: list(pages),
        )
        coordinator._deferred_persistence = SimpleNamespace(
            invalidate_page_visual_revisions=lambda *_args: None,
            cancel_pages=lambda *_args: None,
        )
        coordinator._undo_service = None
        coordinator._sidebar = SimpleNamespace(
            load_takeoff_sidebar_from_memory=lambda *_args: None,
            bid_layers_sidebar=None,
        )
        coordinator._bid_data_cache = {}
        coordinator.takeoff_sidebar = SimpleNamespace(
            restore_selection=lambda pages, active: restored_navigation.append(
                (list(pages), active)
            )
        )
        coordinator._update_page_settings_bar = lambda _page_uid: None
        coordinator._update_plan_view = lambda _page_uid: None
        coordinator._viewer = SimpleNamespace(clear_plan_view=lambda: None)
        coordinator._request_or_defer_mesh_refresh = (
            lambda pages: mesh_refreshes.append(list(pages))
        )
        coordinator._clear_mesh_views_for_scene_update = lambda: terminal_clears.append(
            True
        )
        coordinator._update_export_menu_state = lambda: None
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        coordinator._on_remote_bid_content_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            families=[CollaborationResourceFamily.PAGES.value],
        )
        self.assertEqual(selected_pages, [["page-a"]])
        self.assertEqual(coordinator.ui_state_manager.active_page_uid, "page-a")
        self.assertEqual(restored_navigation, [(["page-a"], "page-a")])
        self.assertEqual(mesh_refreshes, [["page-a"]])
        self.assertEqual(terminal_clears, [])

    def test_remote_first_page_recovers_main_page_and_toolbar_from_empty_bid(self):
        bid_ref = BidRef("sql-db", "bid-1")
        first_page = Page(uid="page-a", name="Page A", sequence=1)
        restored_navigation = []
        toolbar_states = []
        plan_pages = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeMainWindow()
        coordinator._tab_widget = None
        coordinator._status_panel = None
        coordinator.plan_view = SimpleNamespace(
            current_page_uid=None,
            has_active_remote_projection_blocker=lambda: False,
        )
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator._plan_view_handler = None
        coordinator._pending_takeoff_page_uids = None
        coordinator._nav = NavigationStateMachine()
        coordinator._nav.transition_to(NavState.FILE_LOADED_NO_BID)
        coordinator._nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)
        ui_state = SimpleNamespace(
            selected_page_uids=[],
            active_page_uid=None,
            get_selected_bid_ref=lambda: bid_ref,
        )

        def set_page_selection(page_uids):
            ui_state.selected_page_uids = list(page_uids)

        ui_state.set_page_selection = set_page_selection
        coordinator.ui_state_manager = ui_state
        coordinator.project_data = SimpleNamespace(
            get_page=lambda uid: first_page if uid == first_page.uid else None,
            get_all_pages=lambda: [first_page],
            select_pages=lambda page_uids: list(page_uids),
        )
        coordinator._deferred_persistence = SimpleNamespace(
            invalidate_page_visual_revisions=lambda *_args: None,
            cancel_pages=lambda *_args: None,
        )
        coordinator._undo_service = None
        coordinator._page_settings_bar = None
        coordinator._sidebar = SimpleNamespace(
            load_takeoff_sidebar_from_memory=lambda *_args: None,
            bid_layers_sidebar=None,
        )
        coordinator._bid_data_cache = {}

        def restore_selection(page_uids, active_uid):
            restored_navigation.append((list(page_uids), active_uid))

        coordinator.takeoff_sidebar = SimpleNamespace(
            restore_selection=restore_selection
        )
        coordinator._update_page_settings_bar = lambda _page_uid: None

        def update_plan(page_uid):
            coordinator.plan_view.current_page_uid = page_uid
            plan_pages.append(page_uid)

        coordinator._update_plan_view = update_plan
        coordinator._viewer = SimpleNamespace(clear_plan_view=lambda: None)
        coordinator._request_or_defer_mesh_refresh = lambda _pages: None
        coordinator._update_export_menu_state = lambda: toolbar_states.append(
            bool(
                coordinator.ui_state_manager.active_page_uid
                and coordinator.plan_view.current_page_uid
            )
        )
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        coordinator._on_remote_bid_content_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            families=[CollaborationResourceFamily.PAGES.value],
        )
        self.assertEqual(coordinator.ui_state_manager.active_page_uid, "page-a")
        self.assertEqual(coordinator.ui_state_manager.selected_page_uids, ["page-a"])
        self.assertEqual(
            coordinator._nav.current_state,
            NavState.BID_ACTIVE_PAGES_SELECTED,
        )
        self.assertEqual(restored_navigation, [(["page-a"], "page-a")])
        self.assertEqual(plan_pages, ["page-a"])
        self.assertEqual(toolbar_states, [True])

    def test_stale_page_family_completion_reprojects_latest_navigation(self):
        bid_ref = BidRef("sql-db", "bid-1")
        pages = {
            "page-a": Page(uid="page-a", name="Page A", sequence=1),
            "page-b": Page(uid="page-b", name="Page B", sequence=2),
        }
        restored_navigation = []
        invalidated = []
        reprojected = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeMainWindow()
        coordinator._tab_widget = None
        coordinator._status_panel = None
        coordinator.plan_view = None
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator._pending_takeoff_page_uids = None
        ui_state = SimpleNamespace(
            selected_page_uids=["page-b"],
            active_page_uid="page-b",
            get_selected_bid_ref=lambda: bid_ref,
        )

        def set_page_selection(selected):
            ui_state.selected_page_uids = list(selected)

        ui_state.set_page_selection = set_page_selection
        coordinator.ui_state_manager = ui_state
        coordinator.project_data = SimpleNamespace(
            get_page=pages.get,
            get_all_pages=lambda: list(pages.values()),
            select_pages=lambda selected: list(selected),
        )
        coordinator._deferred_persistence = SimpleNamespace(
            invalidate_page_visual_revisions=lambda *args: invalidated.append(args),
            reproject_newer_page_visual_revisions=lambda *args: reprojected.append(
                args
            ),
            cancel_pages=lambda *_args: None,
        )
        coordinator._undo_service = None
        coordinator._sidebar = SimpleNamespace(
            load_takeoff_sidebar_from_memory=lambda *_args: None,
            bid_layers_sidebar=None,
        )
        coordinator.takeoff_sidebar = SimpleNamespace(
            restore_selection=lambda selected, active: restored_navigation.append(
                (list(selected), active)
            )
        )
        coordinator._bid_data_cache = {}
        coordinator._update_page_settings_bar = lambda _page_uid: None
        coordinator._update_plan_view = lambda _page_uid: None
        coordinator._viewer = SimpleNamespace(clear_plan_view=lambda: None)
        coordinator._request_or_defer_mesh_refresh = lambda _pages: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        coordinator._on_remote_bid_content_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            families=[CollaborationResourceFamily.PAGES.value],
            resource_uids_by_family={
                CollaborationResourceFamily.PAGES.value: ["page-a"]
            },
            local_completion=True,
        )
        self.assertEqual(coordinator.ui_state_manager.active_page_uid, "page-b")
        self.assertEqual(restored_navigation, [(["page-b"], "page-b")])
        self.assertEqual(invalidated, [])
        self.assertEqual(reprojected, [("sql-db", ["page-a"], "bid-1")])

    def test_remote_removal_of_all_checked_pages_publishes_recoverable_empty_scene(
        self,
    ):
        bid_ref = BidRef("sql-db", "bid-1")
        mesh_refreshes = []
        terminal_clears = []
        restored_navigation = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeMainWindow()
        coordinator._tab_widget = None
        coordinator._status_panel = None
        coordinator.plan_view = None
        coordinator._plan_view_handler = None
        coordinator._pending_takeoff_page_uids = None
        coordinator._nav = NavigationStateMachine()
        coordinator._nav.transition_to(NavState.FILE_LOADED_NO_BID)
        coordinator._nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)
        coordinator._nav.transition_to(NavState.BID_ACTIVE_PAGES_SELECTED)
        coordinator._placement = SimpleNamespace(
            is_active=False,
            force_exit=lambda: None,
        )
        ui_state = SimpleNamespace(
            selected_page_uids=["deleted-page"],
            active_page_uid="deleted-page",
            get_selected_bid_ref=lambda: bid_ref,
        )

        def set_page_selection(page_uids):
            ui_state.selected_page_uids = list(page_uids)

        ui_state.set_page_selection = set_page_selection
        coordinator.ui_state_manager = ui_state
        coordinator.project_data = SimpleNamespace(
            get_page=lambda _uid: None,
            get_all_pages=lambda: [],
            select_pages=lambda pages: list(pages),
        )
        coordinator._deferred_persistence = SimpleNamespace(
            invalidate_page_visual_revisions=lambda *_args: None,
            cancel_pages=lambda *_args: None,
        )
        coordinator._undo_service = None
        coordinator._sidebar = SimpleNamespace(
            load_takeoff_sidebar_from_memory=lambda *_args: None,
            bid_layers_sidebar=None,
        )
        coordinator._bid_data_cache = {}
        coordinator.takeoff_sidebar = SimpleNamespace(
            restore_selection=lambda pages, active: restored_navigation.append(
                (list(pages), active)
            )
        )
        page_settings_clears = []
        quantity_refreshes = []
        coordinator._page_settings_bar = SimpleNamespace(
            clear_page=lambda: page_settings_clears.append(True)
        )
        coordinator._sidebar.update_conditions_quantities = (
            lambda: quantity_refreshes.append(True)
        )
        coordinator._viewer = SimpleNamespace(clear_plan_view=lambda: None)
        coordinator._request_or_defer_mesh_refresh = (
            lambda pages: mesh_refreshes.append(list(pages))
        )
        coordinator._clear_mesh_views_for_scene_update = lambda: terminal_clears.append(
            True
        )
        toolbar_states = []
        coordinator._update_export_menu_state = lambda: toolbar_states.append(
            bool(coordinator.ui_state_manager.active_page_uid)
        )
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        coordinator._on_remote_bid_content_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            families=[CollaborationResourceFamily.PAGES.value],
        )
        self.assertEqual(mesh_refreshes, [[]])
        self.assertEqual(terminal_clears, [])
        self.assertEqual(restored_navigation, [([], None)])
        self.assertEqual(page_settings_clears, [True])
        self.assertEqual(quantity_refreshes, [True])
        self.assertEqual(coordinator.ui_state_manager.selected_page_uids, [])
        self.assertIsNone(coordinator.ui_state_manager.active_page_uid)
        self.assertEqual(coordinator._nav.current_state, NavState.BID_ACTIVE_NO_PAGES)
        self.assertEqual(toolbar_states, [False])


class UIEventCoordinatorRequestCollaborationEditTests(
    _UIEventCoordinatorTakeoffsChangedFixture
):
    """UIEventCoordinator.request_collaboration_edit."""

    def test_denied_collaboration_lease_reports_the_store_message(self):
        sequence = []
        callbacks = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.main_window = object()
        coordinator._tab_widget = SimpleNamespace(
            currentIndex=lambda: TAB_INDEX_TAKEOFF
        )
        coordinator.ui_state_manager = SimpleNamespace(
            selected_file_path="database",
            get_selected_bid_ref=lambda: None,
        )
        coordinator._prepare_for_modal_mutation_error = (
            lambda database_id: sequence.append(("prepare", database_id))
        )
        coordinator._sql_collaboration = type(
            "SqlCollaboration",
            (),
            {
                "request_local_edit": lambda _self, _database_id, _resources, callback, **_kwargs: callback(
                    EditLeaseResult(False, "The resource is already being edited.")
                )
            },
        )()
        from ost_visualizer.presentation.coordinators import ui_event_coordinator

        old_warning = ui_event_coordinator.show_warning
        ui_event_coordinator.show_warning = lambda *args: sequence.append(
            ("warning", args)
        )
        try:
            coordinator.request_collaboration_edit(
                "database",
                (),
                callbacks.append,
                owning_surface="main-plan",
            )
        finally:
            ui_event_coordinator.show_warning = old_warning
        self.assertEqual(
            callbacks, [EditLeaseResult(False, "The resource is already being edited.")]
        )
        self.assertEqual(sequence[0], ("prepare", "database"))
        self.assertEqual(sequence[1][0], "warning")
        self.assertIn("already being edited", sequence[1][1][2])

    def test_late_collaboration_lease_grant_is_denied_during_cleanup(self):
        callbacks = []
        warnings = []
        pending = []
        released = []
        handle = EditLeaseHandle(
            database_id="database",
            draft_id="draft",
            runtime_generation=1,
            operation_id="edit",
            owning_surface="test",
            resources=(),
        )
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.main_window = object()
        coordinator._tab_widget = SimpleNamespace(
            currentIndex=lambda: TAB_INDEX_TAKEOFF
        )
        coordinator.ui_state_manager = SimpleNamespace(
            selected_file_path="database",
            get_selected_bid_ref=lambda: None,
        )
        coordinator._sql_collaboration = type(
            "SqlCollaboration",
            (),
            {
                "request_local_edit": lambda _self, _database_id, _resources, callback, **_kwargs: pending.append(
                    callback
                ),
                "end_edit_lease": lambda _self, lease_handle: released.append(
                    lease_handle
                ),
            },
        )()
        from ost_visualizer.presentation.coordinators import ui_event_coordinator

        old_warning = ui_event_coordinator.show_warning
        ui_event_coordinator.show_warning = lambda *args: warnings.append(args)
        try:
            coordinator.request_collaboration_edit(
                "database",
                (),
                callbacks.append,
            )
            coordinator._is_cleaning_up = True
            pending[0](EditLeaseResult(True, handle=handle))
        finally:
            ui_event_coordinator.show_warning = old_warning
        self.assertEqual(
            callbacks,
            [
                EditLeaseResult(
                    False, "The edit was cancelled while the view was closing."
                )
            ],
        )
        self.assertEqual(released, [handle])
        self.assertEqual(warnings, [])

    def test_late_condition_editor_lease_grant_is_denied_after_leaving_workspace(self):
        callbacks = []
        warnings = []
        pending = []
        released = []
        resource = ResourceRef("condition", "condition-1", 7)
        handle = EditLeaseHandle(
            database_id="database-a",
            draft_id="draft",
            runtime_generation=1,
            operation_id="edit-condition",
            owning_surface="condition-sidebar",
            resources=(resource,),
        )
        selected_bid = [BidRef("database-a", "7")]
        tab_index = [TAB_INDEX_TAKEOFF]
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.main_window = object()
        coordinator._tab_widget = SimpleNamespace(currentIndex=lambda: tab_index[0])
        coordinator.ui_state_manager = SimpleNamespace(
            selected_file_path="database-a",
            get_selected_bid_ref=lambda: selected_bid[0],
        )
        coordinator._sql_collaboration = type(
            "SqlCollaboration",
            (),
            {
                "request_local_edit": lambda _self, _database_id, _resources, callback, **_kwargs: pending.append(
                    callback
                ),
                "end_edit_lease": lambda _self, lease_handle: released.append(
                    lease_handle
                ),
            },
        )()
        from ost_visualizer.presentation.coordinators import ui_event_coordinator

        old_warning = ui_event_coordinator.show_warning
        ui_event_coordinator.show_warning = lambda *args: warnings.append(args)
        try:
            coordinator.request_collaboration_edit(
                "database-a",
                (resource,),
                callbacks.append,
                operation_id="edit-condition",
                owning_surface="condition-sidebar",
            )
            tab_index[0] = TAB_INDEX_PROJECTS
            pending[0](EditLeaseResult(True, handle=handle))
        finally:
            ui_event_coordinator.show_warning = old_warning
        self.assertEqual(
            callbacks,
            [
                EditLeaseResult(
                    False,
                    "The edit was cancelled because its original context changed.",
                )
            ],
        )
        self.assertEqual(released, [handle])
        self.assertEqual(warnings, [])

    def test_late_database_dialog_lease_grant_is_denied_after_database_switch(self):
        callbacks = []
        pending = []
        released = []
        resource = ResourceRef("employees_collection", "database")
        handle = EditLeaseHandle(
            database_id="database-a",
            draft_id="draft",
            runtime_generation=1,
            operation_id="EmployeesDialog",
            owning_surface="main-window-dialog",
            resources=(resource,),
        )
        state = SimpleNamespace(
            selected_file_path="database-a",
            get_selected_bid_ref=lambda: None,
        )
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.main_window = object()
        coordinator._tab_widget = SimpleNamespace(
            currentIndex=lambda: TAB_INDEX_TAKEOFF
        )
        coordinator.ui_state_manager = state
        coordinator._sql_collaboration = type(
            "SqlCollaboration",
            (),
            {
                "request_local_edit": lambda _self, _database_id, _resources, callback, **_kwargs: pending.append(
                    callback
                ),
                "end_edit_lease": lambda _self, lease_handle: released.append(
                    lease_handle
                ),
            },
        )()
        coordinator.request_collaboration_edit(
            "database-a",
            (resource,),
            callbacks.append,
            operation_id="EmployeesDialog",
            owning_surface="main-window-dialog",
        )
        state.selected_file_path = "database-b"
        pending[0](EditLeaseResult(True, handle=handle))
        self.assertFalse(callbacks[0].granted)
        self.assertEqual(released, [handle])


class UIEventCoordinatorOnFileUnloadedTests(_UIEventCoordinatorTakeoffsChangedFixture):
    """UIEventCoordinator._on_file_unloaded."""

    def test_file_unload_clears_bid_clipboard_before_same_path_reopen(self):
        coordinator = self._make_unload_coordinator(
            selected_file="active.mdb",
            current_file="active.mdb",
        )
        clipboard = BidClipboardService()
        clipboard.cut([BidRef("C:/jobs/active.mdb", "bid-1")])
        coordinator._bid_clipboard = clipboard
        coordinator._on_file_unloaded(
            file_path="C:\\jobs\\active.mdb",
            active_context_removed=False,
        )
        self.assertFalse(clipboard.has_content())
        self.assertFalse(clipboard.is_cut)

    def test_inactive_file_unload_rebuilds_tree_without_clearing_takeoff(self):
        coordinator = self._make_unload_coordinator(
            selected_file="active.mdb",
            current_file="active.mdb",
        )
        embedded = FakeMeshReceiver()
        coordinator.opengl_viewer = embedded
        coordinator._on_file_unloaded(
            file_path="inactive.mdb",
            active_context_removed=False,
        )
        self.assertEqual(coordinator.ui_state_manager.reset_count, 0)
        self.assertEqual(coordinator._viewer.clears, 0)
        self.assertEqual(coordinator._tab_widget.visibility, [])
        self.assertEqual(coordinator.main_window.project_view.builds, 1)
        self.assertEqual(coordinator.main_window.menu_controller.updates, 1)
        self.assertEqual(
            embedded.discarded_camera_states,
            [(None, "inactive.mdb")],
        )

    def test_active_file_unload_switches_to_projects_and_hides_takeoff(self):
        coordinator = self._make_unload_coordinator(
            selected_file="active.mdb",
            current_file=None,
        )
        embedded = FakeMeshReceiver()
        embedded.pending_mutation_uids = {"shared-takeoff"}
        coordinator.opengl_viewer = embedded
        coordinator._pending_3d_takeoff_uids_by_bid = {
            BidRef("active.mdb", "bid-1"): {"shared-takeoff"}
        }
        status_panel = _CollaborationStatusPanel()
        status_panel.set_page_info("Page One")
        status_panel.set_collaboration_state("healthy", "Connected")
        status_panel.set_collaboration_mutation_state("recovering", 1, "Recovering")
        coordinator._status_panel = status_panel
        coordinator._on_file_unloaded(
            file_path="active.mdb",
            active_context_removed=True,
        )
        self.assertEqual(coordinator.ui_state_manager.reset_count, 1)
        self.assertEqual(coordinator._viewer.clears, 1)
        self.assertEqual(coordinator._tab_widget.visibility, [(1, False), (2, False)])
        self.assertEqual(coordinator._tab_widget.currentIndex(), 0)
        self.assertEqual(coordinator.main_window.project_view.resets, 1)
        self.assertEqual(coordinator.main_window.menu_controller.updates, 1)
        self.assertEqual(embedded.clear_calls, 1)
        self.assertEqual(embedded.pending_mutation_uids, set())
        self.assertEqual(coordinator._pending_3d_takeoff_uids_by_bid, {})
        self.assertEqual(
            embedded.discarded_camera_states,
            [(None, "active.mdb")],
        )
        self.assertEqual(status_panel.page_info, "")
        self.assertEqual(status_panel.presence_states[-1], [])
        self.assertEqual(status_panel.mutation_states[-1], ("", 0, ""))
        self.assertEqual(status_panel.states[-1], ("stopped", ""))


class UIEventCoordinatorHandlePageSelectionTests(
    _UIEventCoordinatorTakeoffsChangedFixture
):
    """UIEventCoordinator.handle_page_selection."""

    def test_page_uncheck_switch_and_recheck_publish_each_authoritative_scene(self):
        coordinator, bid_ref, embedded, detached = (
            self._make_3d_page_selection_coordinator()
        )
        generation = 0

        def select_and_publish(page_uids):
            nonlocal generation
            coordinator.handle_page_selection(page_uids)
            generation += 1
            identity = scene_identity(bid_ref, generation, page_uids)
            coordinator._on_native_scene_updated(
                geometries=[],
                scene_identity=identity,
                scene_failed=False,
            )
            return identity

        page_a_first = select_and_publish(["page-a"])
        empty_after_a = select_and_publish([])
        page_b = select_and_publish(["page-b"])
        empty_after_b = select_and_publish([])
        page_a_again = select_and_publish(["page-a"])
        expected_refreshes = [
            ["page-a"],
            [],
            ["page-b"],
            [],
            ["page-a"],
        ]
        self.assertEqual(
            coordinator.visualization_service.mesh_pages, expected_refreshes
        )
        self.assertEqual(embedded.clear_calls, 0)
        self.assertEqual(detached.clear_calls, 0)
        expected_identities = [
            page_a_first,
            empty_after_a,
            page_b,
            empty_after_b,
            page_a_again,
        ]
        self.assertEqual(
            [options["scene_identity"] for _args, options in embedded.mesh_calls],
            expected_identities,
        )
        self.assertEqual(
            [options["scene_identity"] for _args, options in detached.mesh_calls],
            expected_identities,
        )

    def test_obsolete_page_callback_is_rejected_after_rapid_page_switch(self):
        coordinator, bid_ref, embedded, detached = (
            self._make_3d_page_selection_coordinator()
        )
        coordinator.handle_page_selection(["page-a"])
        page_a = scene_identity(bid_ref, 10, ["page-a"])
        coordinator.handle_page_selection(["page-b"])
        coordinator._on_native_scene_updated(
            geometries=[],
            scene_identity=page_a,
            scene_failed=False,
        )
        self.assertEqual(embedded.mesh_calls, [])
        self.assertEqual(detached.mesh_calls, [])
        page_b = scene_identity(bid_ref, 11, ["page-b"])
        coordinator._on_native_scene_updated(
            geometries=[],
            scene_identity=page_b,
            scene_failed=False,
        )
        self.assertEqual(embedded.mesh_calls[0][1]["scene_identity"], page_b)
        self.assertEqual(detached.mesh_calls[0][1]["scene_identity"], page_b)

    def test_multiple_checked_pages_and_removal_use_canonical_scene_identity(self):
        coordinator, bid_ref, embedded, detached = (
            self._make_3d_page_selection_coordinator()
        )
        coordinator.handle_page_selection(["page-b", "page-a"])
        both_pages = scene_identity(bid_ref, 20, ["page-b", "page-a"])
        coordinator._on_native_scene_updated(
            geometries=[],
            scene_identity=both_pages,
            scene_failed=False,
        )
        coordinator.handle_page_selection(["page-b"])
        page_b = scene_identity(bid_ref, 21, ["page-b"])
        coordinator._on_native_scene_updated(
            geometries=[],
            scene_identity=page_b,
            scene_failed=False,
        )
        self.assertEqual(
            coordinator.visualization_service.mesh_pages,
            [["page-a", "page-b"], ["page-b"]],
        )
        self.assertEqual(
            [call[1]["scene_identity"] for call in embedded.mesh_calls],
            [both_pages, page_b],
        )
        self.assertEqual(
            [call[1]["scene_identity"] for call in detached.mesh_calls],
            [both_pages, page_b],
        )

    def test_duplicate_page_selection_event_does_not_restart_scene_generation(self):
        coordinator, _bid_ref, embedded, detached = (
            self._make_3d_page_selection_coordinator()
        )
        coordinator.handle_page_selection(["page-b", "page-a", "page-a"])
        coordinator.handle_page_selection(["page-a", "page-b"])
        self.assertEqual(
            coordinator.visualization_service.mesh_pages,
            [["page-a", "page-b"]],
        )
        self.assertEqual(len(embedded.scene_refreshes), 1)
        self.assertEqual(len(detached.scene_refreshes), 1)

    def test_3d_page_toggles_preserve_active_takeoff_cursor_and_navigation(self):
        coordinator, _bid_ref, _embedded, _detached = (
            self._make_3d_page_selection_coordinator()
        )
        coordinator._nav.transition_to(NavState.BID_ACTIVE_PAGES_SELECTED)
        coordinator._nav.transition_to(NavState.PLACE_MODE)
        coordinator.plan_view = SimpleNamespace(cursor_mode="place")
        coordinator.handle_page_selection(["page-a"])
        coordinator.visualization_service.mesh_pages.clear()
        coordinator.handle_page_selection([])
        coordinator.handle_page_selection(["page-b"])
        coordinator.handle_page_selection(["page-b"])
        self.assertEqual(coordinator.ui_state_manager.active_page_uid, "page-a")
        self.assertEqual(coordinator.plan_view.cursor_mode, "place")
        self.assertEqual(coordinator._nav.current_state, NavState.PLACE_MODE)
        self.assertEqual(
            coordinator.visualization_service.mesh_pages,
            [[], ["page-b"]],
        )

    def test_failed_scene_is_not_replayed_and_same_selection_can_retry(self):
        coordinator, bid_ref, embedded, detached = (
            self._make_3d_page_selection_coordinator()
        )
        coordinator.handle_page_selection(["page-a"])
        failed_identity = scene_identity(bid_ref, 25, ["page-a"])
        coordinator._on_native_scene_updated(
            geometries=[],
            scene_identity=failed_identity,
            scene_failed=True,
        )
        self.assertEqual(embedded.scene_failures, [failed_identity])
        self.assertEqual(detached.scene_failures, [failed_identity])
        self.assertEqual(embedded.mesh_calls, [])
        self.assertEqual(detached.mesh_calls, [])
        self.assertIsNone(coordinator._last_mesh_scene)
        self.assertTrue(coordinator._mesh_scene_dirty)
        self.assertEqual(coordinator._dirty_mesh_page_uids, {"page-a"})
        coordinator.handle_page_selection(["page-a"])
        self.assertEqual(
            coordinator.visualization_service.mesh_pages,
            [["page-a"], ["page-a"]],
        )
        retry_identity = scene_identity(bid_ref, 26, ["page-a"])
        coordinator._on_native_scene_updated(
            geometries=[],
            scene_identity=retry_identity,
            scene_failed=False,
        )
        self.assertEqual(embedded.mesh_calls[0][1]["scene_identity"], retry_identity)
        self.assertEqual(detached.mesh_calls[0][1]["scene_identity"], retry_identity)
        self.assertFalse(coordinator._mesh_scene_dirty)

    def test_failed_same_bid_refresh_retains_last_accepted_replay_scene(self):
        coordinator, bid_ref, embedded, detached = (
            self._make_3d_page_selection_coordinator()
        )
        coordinator.handle_page_selection(["page-a"])
        cached_identity = scene_identity(bid_ref, 24, ["page-a"])
        cached_scene = mesh_publication(
            ([], [], [], []),
            cached_identity,
            {"page-a": 0.0},
        )
        coordinator._last_mesh_scene = cached_scene
        failed_identity = scene_identity(bid_ref, 25, ["page-a"])
        coordinator._on_native_scene_updated(
            geometries=[],
            scene_identity=failed_identity,
            scene_failed=True,
        )
        self.assertIs(coordinator._last_mesh_scene, cached_scene)
        self.assertEqual(embedded.scene_failures, [failed_identity])
        self.assertEqual(detached.scene_failures, [failed_identity])
        self.assertTrue(coordinator._mesh_scene_dirty)

    def test_database_refresh_invalidates_and_republishes_unchanged_page_scene_once(
        self,
    ):
        coordinator, _bid_ref, embedded, detached = (
            self._make_3d_page_selection_coordinator()
        )
        coordinator.handle_page_selection(["page-a"])
        coordinator.visualization_service.mesh_pages.clear()
        embedded.scene_refreshes.clear()
        detached.scene_refreshes.clear()
        coordinator._deferred_persistence = SimpleNamespace(
            flush_for_file=lambda _file_path: True
        )
        coordinator._placement = SimpleNamespace()
        coordinator._nav = SimpleNamespace(start_refresh=lambda *_args, **_kwargs: True)
        coordinator._do_file_refresh = lambda: None
        coordinator._finish_refresh = lambda: coordinator._update_page_selection(
            ["page-a"]
        )
        coordinator._on_database_refreshed(file_path="active.mdb")
        self.assertEqual(coordinator.visualization_service.cancelled_mesh_refreshes, 1)
        self.assertEqual(embedded.clear_calls, 1)
        self.assertEqual(detached.clear_calls, 1)
        self.assertEqual(coordinator.visualization_service.mesh_pages, [["page-a"]])
        self.assertEqual(len(embedded.scene_refreshes), 1)
        self.assertEqual(len(detached.scene_refreshes), 1)
        self.assertTrue(coordinator._pending_dirty_mesh_refresh)

    def test_page_name_fallback_preserves_accepted_scene_without_mesh_generation(self):
        from ost_visualizer.application.services.base_write_service import (
            BaseWriteService,
        )
        from ost_visualizer.application.services.project_write_service import (
            ProjectWriteService,
        )

        coordinator, bid_ref, embedded, detached = (
            self._make_3d_page_selection_coordinator()
        )
        coordinator.handle_page_selection(["page-a"])
        coordinator.visualization_service.mesh_pages.clear()
        embedded.scene_refreshes.clear()
        detached.scene_refreshes.clear()
        coordinator._deferred_persistence = SimpleNamespace(
            flush_for_file=lambda _path: True
        )
        coordinator._placement = SimpleNamespace()
        coordinator._nav = SimpleNamespace(start_refresh=lambda *_args, **_kwargs: True)
        coordinator._do_file_refresh = lambda: None
        coordinator._finish_refresh = lambda: coordinator._update_page_selection(
            ["page-a"]
        )
        bus = EventBus()
        bus.subscribe(AppEvents.DATABASE_REFRESHED, coordinator._on_database_refreshed)
        service = ProjectWriteService.__new__(ProjectWriteService)
        BaseWriteService.__init__(service, lambda _path: True, bus)
        service._bid_write_guard = SimpleNamespace(
            blocks_active_locked_bid_write=lambda _path: False
        )
        service._active_bid_uid_for = lambda _path: 1
        service._execute_boolean_resource_mutation = (
            lambda _path, _resources, _operation, save, _fields: save()
        )
        service._save_page_name = SimpleNamespace(execute=lambda *_args: True)
        service._project_data = SimpleNamespace(get_page=lambda _uid: None)
        self.assertTrue(service.save_page_name(bid_ref.file_path, "page-a", "Renamed"))
        self.assertEqual(coordinator.visualization_service.mesh_pages, [])
        self.assertEqual(embedded.clear_calls, 0)
        self.assertEqual(detached.clear_calls, 0)
        self.assertEqual(embedded.scene_refreshes, [])
        self.assertEqual(detached.scene_refreshes, [])

    def test_ordinary_layer_rename_preserves_accepted_scene_without_generation(self):
        from ost_visualizer.application.services.base_write_service import (
            BaseWriteService,
        )
        from ost_visualizer.application.services.project_write_service import (
            ProjectWriteService,
        )

        coordinator, bid_ref, embedded, detached = (
            self._make_3d_page_selection_coordinator()
        )
        coordinator.handle_page_selection(["page-a"])
        coordinator.visualization_service.mesh_pages.clear()
        embedded.scene_refreshes.clear()
        detached.scene_refreshes.clear()
        coordinator._deferred_persistence = SimpleNamespace(
            flush_for_file=lambda _path: True
        )
        coordinator._placement = SimpleNamespace()
        coordinator._nav = SimpleNamespace(start_refresh=lambda *_args, **_kwargs: True)
        coordinator._do_file_refresh = lambda: None
        coordinator._finish_refresh = lambda: coordinator._update_page_selection(
            ["page-a"]
        )
        bus = EventBus()
        bus.subscribe(AppEvents.DATABASE_REFRESHED, coordinator._on_database_refreshed)
        service = ProjectWriteService.__new__(ProjectWriteService)
        BaseWriteService.__init__(service, lambda _path: True, bus)
        service._bid_write_guard = SimpleNamespace(
            blocks_active_locked_bid_write=lambda _path: False
        )
        service._active_bid_uid_for = lambda _path: 1
        service._execute_boolean_resource_mutation = (
            lambda _path, _resources, _operation, save, _fields: save()
        )
        layers = [BidLayer("layer-1", "1", "Walls", True, 1)]
        service._project_data = SimpleNamespace(
            get_bid_layer_snapshot=lambda: list(layers)
        )
        service._update_layer_name = SimpleNamespace(execute=lambda *_args: True)

        def reload(_path):
            layers[0] = BidLayer("layer-1", "1", "Renamed walls", True, 1)
            return True

        service._reload_database = reload
        self.assertTrue(
            service.update_layer_name(bid_ref.file_path, "layer-1", "Renamed walls")
        )
        self.assertEqual(coordinator.visualization_service.mesh_pages, [])
        self.assertEqual(embedded.clear_calls, 0)
        self.assertEqual(detached.clear_calls, 0)
        self.assertEqual(embedded.scene_refreshes, [])
        self.assertEqual(detached.scene_refreshes, [])

    def test_elevation_change_keeps_accepted_meshes_until_replacement_is_ready(self):
        coordinator, bid_ref, embedded, detached = (
            self._make_3d_page_selection_coordinator()
        )
        coordinator.main_window = FakeMainWindow()
        coordinator.handle_page_selection(["page-a"])
        coordinator.ui_state_manager.highlighted_condition_uids = {"condition-1"}
        coordinator.ui_state_manager.place_condition_uid = None
        coordinator.ui_state_manager.place_condition_uids = []

        def set_highlighted_conditions(uids):
            coordinator.ui_state_manager.highlighted_condition_uids = set(uids)

        coordinator.ui_state_manager.set_highlighted_conditions = (
            set_highlighted_conditions
        )
        coordinator.project_data.get_bid_conditions = lambda: {
            "condition-1": Condition(uid="condition-1")
        }
        coordinator._placement = FakePlacement()
        coordinator._sidebar.refresh_conditions_from_memory = lambda: None
        coordinator._restore_sidebar_highlight = lambda _uids, reveal=False: None
        coordinator._update_plan_view_for_active = lambda **_options: None
        coordinator._undo_service = SimpleNamespace(
            clear=lambda: self.fail("local completion must preserve undo history")
        )
        coordinator.visualization_service.mesh_pages.clear()
        embedded.scene_refreshes.clear()
        detached.scene_refreshes.clear()
        cached_identity = scene_identity(bid_ref, 24, ["page-a"])
        cached_scene = mesh_publication(
            ([], [], [], []),
            cached_identity,
            {"page-a": 0.0},
        )
        coordinator._last_mesh_scene = cached_scene
        coordinator._on_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["condition-1"],
            changed_fields=["name", "z_value"],
        )
        self.assertEqual(coordinator.visualization_service.mesh_pages, [["page-a"]])
        self.assertEqual(embedded.clear_calls, 0)
        self.assertEqual(detached.clear_calls, 0)
        self.assertEqual(embedded.scene_refreshes, [(bid_ref, ("page-a",))])
        self.assertEqual(detached.scene_refreshes, [(bid_ref, ("page-a",))])
        self.assertIs(coordinator._last_mesh_scene, cached_scene)
        failed_identity = scene_identity(bid_ref, 25, ["page-a"])
        coordinator._on_native_scene_updated(
            geometries=[],
            scene_identity=failed_identity,
            scene_failed=True,
        )
        self.assertIs(coordinator._last_mesh_scene, cached_scene)
        self.assertEqual(embedded.scene_failures, [failed_identity])
        self.assertEqual(detached.scene_failures, [failed_identity])

    def test_page_selection_without_bid_does_not_enter_bid_page_state(self):
        coordinator = self._make_page_selection_coordinator(
            bid_ref=None, current_state=NavState.FILE_LOADED_NO_BID
        )
        logger = "ost_visualizer.presentation.coordinators.navigation_state_machine"
        with self.assertNoLogs(logger, level="WARNING"):
            coordinator.handle_page_selection(["page-1"])
        self.assertEqual(coordinator._nav.current_state, NavState.FILE_LOADED_NO_BID)
        self.assertEqual(coordinator.project_data.select_calls, [])
        self.assertEqual(coordinator.ui_state_manager.set_page_selection_calls, [])

    def test_page_selection_does_not_own_2d_navigation_state(self):
        bid_ref = BidRef("active.mdb", "bid-1")
        coordinator = self._make_page_selection_coordinator(
            bid_ref=bid_ref, current_state=NavState.FILE_LOADED_NO_BID
        )
        logger = "ost_visualizer.presentation.coordinators.navigation_state_machine"
        with self.assertNoLogs(logger, level="WARNING"):
            coordinator.handle_page_selection(["page-1"])
        self.assertEqual(
            coordinator.project_data.select_calls,
            [["page-1"]],
        )
        self.assertEqual(
            coordinator._nav.current_state,
            NavState.FILE_LOADED_NO_BID,
        )

    def test_invalid_page_selection_uses_filtered_empty_selection_for_nav_state(self):
        bid_ref = BidRef("active.mdb", "bid-1")
        coordinator = self._make_page_selection_coordinator(
            bid_ref=bid_ref, current_state=NavState.BID_ACTIVE_NO_PAGES
        )
        logger = "ost_visualizer.presentation.coordinators.navigation_state_machine"
        with self.assertNoLogs(logger, level="WARNING"):
            coordinator.handle_page_selection(["missing-page"])
        self.assertEqual(coordinator._nav.current_state, NavState.BID_ACTIVE_NO_PAGES)
        self.assertEqual(coordinator.ui_state_manager.selected_page_uids, [])


class UIEventCoordinatorSyncNavigationForActivePageTests(
    _UIEventCoordinatorTakeoffsChangedFixture
):
    """UIEventCoordinator._sync_navigation_for_active_page."""

    def test_deleted_last_active_page_returns_bid_to_no_page_state(self):
        bid_ref = BidRef("active.mdb", "bid-1")
        coordinator = self._make_page_selection_coordinator(
            bid_ref=bid_ref,
            current_state=NavState.BID_ACTIVE_PAGES_SELECTED,
        )
        coordinator._placement = FakePlacement()
        logger = "ost_visualizer.presentation.coordinators.navigation_state_machine"
        with self.assertNoLogs(logger, level="WARNING"):
            coordinator._sync_navigation_for_active_page(bid_ref, None)
        self.assertEqual(coordinator._nav.current_state, NavState.BID_ACTIVE_NO_PAGES)

    def test_active_page_signal_projects_bid_base_before_selected_page_state(self):
        bid_ref = BidRef("active.mdb", "bid-1")
        coordinator = self._make_page_selection_coordinator(
            bid_ref=bid_ref,
            current_state=NavState.FILE_LOADED_NO_BID,
        )
        logger = "ost_visualizer.presentation.coordinators.navigation_state_machine"
        with self.assertNoLogs(logger, level="WARNING"):
            coordinator._sync_navigation_for_active_page(bid_ref, "page-1")
        self.assertEqual(
            coordinator._nav.current_state,
            NavState.BID_ACTIVE_PAGES_SELECTED,
        )

    def test_sql_bid_page_restore_from_no_file_projects_each_required_stage(self):
        coordinator = navigation_status_coordinator(tab_index=TAB_INDEX_TAKEOFF)
        coordinator._nav = NavigationStateMachine()
        bid_ref = BidRef("sql-database", "bid-1")
        coordinator._activate_takeoff_workspace = (
            lambda: coordinator._sync_navigation_for_active_page(bid_ref, "page-1")
        )
        logger = "ost_visualizer.presentation.coordinators.navigation_state_machine"
        with self.assertNoLogs(logger, level="WARNING"):
            coordinator.handle_bid_selection(bid_ref)
            coordinator.project_operations.complete(True)
        self.assertEqual(
            coordinator._nav.current_state, NavState.BID_ACTIVE_PAGES_SELECTED
        )


class UIEventCoordinatorOnTakeoffsChangedTests(
    _UIEventCoordinatorTakeoffsChangedFixture
):
    """UIEventCoordinator._on_takeoffs_changed."""

    def test_takeoffs_changed_refreshes_page_indicator_and_area_usage(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = FakeUiState()
        coordinator.project_data = FakeProjectData()
        coordinator.takeoff_sidebar = FakeTakeoffSidebar()
        coordinator._page_settings_bar = FakePageSettingsBar()
        coordinator._viewer = FakeViewer()
        coordinator._sidebar = FakeSidebar()
        coordinator._toolbar = FakeToolbar()
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: False
        )
        coordinator.main_window = FakeMainWindow()
        configure_mesh_state(coordinator)
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        coordinator._on_takeoffs_changed(
            page_uid="page-1", takeoff_uids=["t-1"], condition_uids=["c1"]
        )
        self.assertEqual(coordinator.takeoff_sidebar.calls, [("page-1", True)])
        self.assertEqual(
            coordinator._page_settings_bar.calls,
            [({"0", "area-1"}, {"area-1"})],
        )
        self.assertEqual(coordinator._viewer.plan_pages, ["page-1"])
        self.assertEqual(coordinator._viewer.changed_takeoff_uids, [["t-1"]])
        self.assertEqual(coordinator._viewer.viewer_pages, [])
        self.assertEqual(coordinator.visualization_service.mesh_pages, [])
        self.assertTrue(coordinator._mesh_scene_dirty)
        self.assertEqual(coordinator._dirty_mesh_page_uids, {"page-1"})
        self.assertEqual(coordinator._sidebar.quantity_updates, 1)
        self.assertEqual(coordinator._sidebar.condition_quantity_updates, [["c1"]])
        self.assertEqual(coordinator._sidebar.condition_refreshes, 0)
        self.assertEqual(coordinator._sidebar.condition_summary_loads, 0)
        self.assertEqual(coordinator.main_window.menu_controller.updates, 1)
        self.assertEqual(coordinator._toolbar.refreshes, 1)

    def test_multi_page_takeoff_event_projects_and_generates_once(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = FakeUiState()
        coordinator.project_data = FakeProjectData()
        coordinator.takeoff_sidebar = FakeTakeoffSidebar()
        coordinator._page_settings_bar = FakePageSettingsBar()
        coordinator._viewer = FakeViewer()
        coordinator._sidebar = FakeSidebar()
        coordinator._toolbar = FakeToolbar()
        coordinator.main_window = FakeMainWindow()
        configure_mesh_state(
            coordinator,
            tab_index=TAB_INDEX_TAKEOFF,
            view_index=0,
        )
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        scans = []
        original_scan = coordinator.project_data.get_area_uids_with_takeoff

        def scan():
            scans.append(True)
            return original_scan()

        coordinator.project_data.get_area_uids_with_takeoff = scan
        coordinator._on_takeoffs_changed(
            page_uids=["page-1", "page-2", "page-1"],
            takeoff_uids=["t-1", "t-2"],
            condition_uids=["c1"],
        )
        self.assertEqual(coordinator._viewer.plan_pages, ["page-1"])
        self.assertEqual(coordinator.visualization_service.mesh_pages, [["page-1"]])
        self.assertEqual(
            coordinator.takeoff_sidebar.calls,
            [("page-1", True), ("page-2", False)],
        )
        self.assertEqual(coordinator.main_window.menu_controller.updates, 1)
        self.assertEqual(coordinator._toolbar.refreshes, 1)
        self.assertEqual(len(scans), 1)
        self.assertEqual(
            coordinator._page_settings_bar.calls, [({"0", "area-1"}, {"area-1"})]
        )
        coordinator.ui_state_manager.get_selected_bid_ref = lambda: BidRef(
            "sql-db", "bid-1"
        )
        coordinator._undo_service = None
        coordinator._selected_takeoff_uids = ()
        coordinator._plan_view_handler = None
        coordinator.plan_view = SimpleNamespace(
            has_active_remote_projection_blocker=lambda: False
        )
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        for deferred in (False, True):
            for local in (False, True):
                with self.subTest(deferred=deferred, local=local):
                    scans.clear()
                    coordinator._page_settings_bar.calls.clear()
                    coordinator.takeoff_sidebar.calls.clear()
                    coordinator._on_remote_bid_content_changed(
                        database_id="sql-db",
                        bid_uid="bid-1",
                        families=["takeoffs"],
                        affected_page_uids_by_family={"takeoffs": ["page-1", "page-2"]},
                        defer_plan_projection=deferred,
                        local_completion=local,
                    )
                    self.assertEqual(len(scans), 1)
                    self.assertEqual(
                        coordinator._page_settings_bar.calls,
                        [({"0", "area-1"}, {"area-1"})],
                    )
                    self.assertEqual(
                        coordinator.takeoff_sidebar.calls,
                        [("page-1", True), ("page-2", False)],
                    )

    def test_takeoffs_changed_loads_summary_when_summary_tab_is_active(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: False
        )
        coordinator.ui_state_manager = FakeUiState()
        coordinator.project_data = FakeProjectData()
        coordinator.takeoff_sidebar = FakeTakeoffSidebar()
        coordinator._page_settings_bar = FakePageSettingsBar()
        coordinator._viewer = FakeViewer()
        coordinator._sidebar = FakeSidebar()
        coordinator._toolbar = FakeToolbar()
        coordinator.main_window = FakeMainWindow()
        configure_mesh_state(coordinator, tab_index=2)
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        coordinator._on_takeoffs_changed(
            page_uid="page-1", takeoff_uids=["t-1"], condition_uids=["c1"]
        )
        self.assertEqual(coordinator._sidebar.condition_summary_loads, 1)

    def test_takeoffs_changed_publishes_authoritative_empty_model_selection(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = FakeUiState()
        coordinator.project_data = FakeProjectData()
        coordinator.project_data.selected_page_uids = []
        coordinator.takeoff_sidebar = FakeTakeoffSidebar()
        coordinator._page_settings_bar = FakePageSettingsBar()
        coordinator._viewer = FakeViewer()
        coordinator._sidebar = FakeSidebar()
        coordinator._toolbar = FakeToolbar()
        coordinator.main_window = FakeMainWindow()
        configure_mesh_state(coordinator, visualization=FakeVisualization())
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        coordinator._on_takeoffs_changed(page_uid="page-1", takeoff_uids=["t-1"])
        self.assertEqual(coordinator._viewer.plan_pages, ["page-1"])
        self.assertEqual(coordinator.visualization_service.mesh_pages, [[]])
        self.assertEqual(coordinator.visualization_service.cancelled_mesh_refreshes, 0)
        self.assertFalse(coordinator._mesh_scene_dirty)

    def test_takeoffs_changed_refreshes_mesh_live_when_embedded_3d_active(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = FakeUiState()
        coordinator.project_data = FakeProjectData()
        coordinator.takeoff_sidebar = FakeTakeoffSidebar()
        coordinator._page_settings_bar = FakePageSettingsBar()
        coordinator._viewer = FakeViewer()
        coordinator._sidebar = FakeSidebar()
        coordinator._toolbar = FakeToolbar()
        coordinator.main_window = FakeMainWindow()
        configure_mesh_state(coordinator, tab_index=TAB_INDEX_TAKEOFF, view_index=0)
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        coordinator._on_takeoffs_changed(page_uid="page-1", takeoff_uids=["t-1"])
        self.assertEqual(coordinator.visualization_service.mesh_pages, [["page-1"]])
        self.assertFalse(coordinator._mesh_scene_dirty)

    def test_takeoffs_changed_refreshes_mesh_live_when_detached_mesh_visible(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = FakeUiState()
        coordinator.project_data = FakeProjectData()
        coordinator.takeoff_sidebar = FakeTakeoffSidebar()
        coordinator._page_settings_bar = FakePageSettingsBar()
        coordinator._viewer = FakeViewer()
        coordinator._sidebar = FakeSidebar()
        coordinator._toolbar = FakeToolbar()
        coordinator.main_window = FakeMainWindow()
        mesh_window = FakeMeshReceiver(visible=True)
        configure_mesh_state(coordinator, mesh_window=mesh_window)
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        coordinator._on_takeoffs_changed(page_uid="page-1", takeoff_uids=["t-1"])
        self.assertEqual(coordinator.visualization_service.mesh_pages, [["page-1"]])
        self.assertFalse(coordinator._mesh_scene_dirty)

    def test_hidden_2d_takeoff_changes_only_invalidate_rendered_pages(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = FakeUiState()
        coordinator.project_data = FakeProjectData()
        coordinator.takeoff_sidebar = FakeTakeoffSidebar()
        coordinator._page_settings_bar = FakePageSettingsBar()
        coordinator._viewer = FakeViewer()
        coordinator._sidebar = FakeSidebar()
        coordinator._toolbar = FakeToolbar()
        coordinator.main_window = FakeMainWindow()
        coordinator._placement = FakePlacement()
        coordinator._is_cleaning_up = False
        coordinator._nav = FakeNav()
        coordinator.ui_access_manager = FakeMeshAccess()
        coordinator._plan_view_signaler = FakeMeshPlanSignaler()
        configure_mesh_state(coordinator, opengl_viewer=FakeMeshReceiver())
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        coordinator._sync_page_info_status = lambda: None
        coordinator._on_takeoffs_changed(page_uid="page-1", takeoff_uids=["t-1"])
        coordinator._on_takeoffs_changed(page_uid="page-2", takeoff_uids=["t-2"])
        self.assertEqual(coordinator.visualization_service.mesh_pages, [])
        self.assertEqual(coordinator._dirty_mesh_page_uids, {"page-1"})
        coordinator._view_stack.setCurrentIndex(0)
        coordinator._on_view_stack_changed(0)
        self.assertEqual(coordinator.visualization_service.mesh_pages, [["page-1"]])
        self.assertTrue(coordinator._pending_dirty_mesh_refresh)
        active_ref = BidRef("test.mdb", "bid-1")
        coordinator.ui_state_manager.get_selected_bid_ref = lambda: active_ref
        coordinator._on_native_scene_updated(
            geometries=[],
            scene_identity=scene_identity(active_ref, 1),
            scene_failed=False,
        )
        self.assertFalse(coordinator._mesh_scene_dirty)
        self.assertFalse(coordinator._pending_dirty_mesh_refresh)

    def test_unrendered_page_change_preserves_current_scene_without_rebuild(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = FakeUiState()
        coordinator.project_data = FakeProjectData()
        coordinator.takeoff_sidebar = FakeTakeoffSidebar()
        coordinator._page_settings_bar = FakePageSettingsBar()
        coordinator._viewer = FakeViewer()
        coordinator._sidebar = FakeSidebar()
        coordinator._toolbar = FakeToolbar()
        coordinator.main_window = FakeMainWindow()
        cached_scene = mesh_publication(
            ("vertices", "normals", "indices", "colors"),
            scene_identity(BidRef("test.mdb", "bid-1"), 7),
            {"page-1": 7.0},
        )
        embedded = FakeMeshReceiver()
        configure_mesh_state(
            coordinator,
            view_index=0,
            opengl_viewer=embedded,
            last_mesh_scene=cached_scene,
        )
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        coordinator._on_takeoffs_changed(
            page_uid="page-2",
            takeoff_uids=["takeoff-on-unrendered-page"],
        )
        self.assertIs(coordinator._last_mesh_scene, cached_scene)
        self.assertEqual(embedded.scene_refreshes, [])
        self.assertEqual(coordinator.visualization_service.mesh_pages, [])
        self.assertFalse(coordinator._mesh_scene_dirty)


class UIEventCoordinatorSetMeshWindowVisibleTests(
    _UIEventCoordinatorTakeoffsChangedFixture
):
    """UIEventCoordinator.set_mesh_window_visible."""

    def test_opening_detached_mesh_window_with_dirty_state_replays_then_refreshes(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = FakeUiState()
        coordinator.project_data = FakeProjectData()
        coordinator._icon_provider = None
        coordinator._color_service = None
        coordinator._plan_view_handler = None
        coordinator._mesh_window = None
        coordinator._mesh_window_action = None
        last_mesh_scene = mesh_publication(
            ("stale-vertices", "stale-normals", "stale-indices", "stale-colors"),
            scene_identity(BidRef("test.mdb", "bid-1"), 1),
            {"page-1": 1.0},
        )
        coordinator.main_window = FakeMainWindow()
        configure_mesh_state(coordinator, last_mesh_scene=last_mesh_scene)
        coordinator._mesh_scene_dirty = True
        coordinator._dirty_mesh_page_uids = {"page-1"}
        from ost_visualizer.presentation.coordinators import ui_event_coordinator

        original = ui_event_coordinator.MeshViewWindow
        ui_event_coordinator.MeshViewWindow = FakeConstructedMeshWindow
        try:
            coordinator.set_mesh_window_visible(True)
        finally:
            ui_event_coordinator.MeshViewWindow = original
        self.assertEqual(coordinator.visualization_service.mesh_pages, [["page-1"]])
        self.assertEqual(len(coordinator._mesh_window.mesh_calls), 1)
        self.assertEqual(
            coordinator._mesh_window.mesh_calls[0][0],
            ("stale-vertices", "stale-normals", "stale-indices", "stale-colors"),
        )
        self.assertEqual(
            coordinator._mesh_window.scene_refreshes,
            [
                (BidRef("test.mdb", "bid-1"), ("page-1",)),
                (BidRef("test.mdb", "bid-1"), ("page-1",)),
            ],
        )

    def test_opening_detached_mesh_window_without_dirty_state_replays_cached_mesh(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = FakeUiState()
        coordinator.project_data = FakeProjectData()
        coordinator._icon_provider = None
        coordinator._color_service = None
        coordinator._plan_view_handler = None
        coordinator._mesh_window = None
        coordinator._mesh_window_action = None
        mesh_args = ("vertices", "normals", "indices", "colors")
        active_ref = BidRef("test.mdb", "bid-1")
        coordinator.ui_state_manager.get_selected_bid_ref = lambda: active_ref
        last_mesh_scene = mesh_publication(
            mesh_args,
            scene_identity(active_ref, 1),
            {"page-1": 1.0},
        )
        coordinator.main_window = FakeMainWindow()
        configure_mesh_state(coordinator, last_mesh_scene=last_mesh_scene)
        from ost_visualizer.presentation.coordinators import ui_event_coordinator

        original = ui_event_coordinator.MeshViewWindow
        ui_event_coordinator.MeshViewWindow = FakeConstructedMeshWindow
        try:
            coordinator.set_mesh_window_visible(True)
        finally:
            ui_event_coordinator.MeshViewWindow = original
        self.assertEqual(coordinator.visualization_service.mesh_pages, [])
        self.assertEqual(len(coordinator._mesh_window.mesh_calls), 1)

    def test_opening_detached_mesh_waits_for_newer_matching_generation(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        active_ref = BidRef("test.mdb", "bid-1")
        coordinator.ui_state_manager = FakeUiState()
        coordinator.ui_state_manager.get_selected_bid_ref = lambda: active_ref
        coordinator.project_data = FakeProjectData()
        coordinator._icon_provider = None
        coordinator._color_service = None
        coordinator._plan_view_handler = None
        coordinator._mesh_window = None
        coordinator._mesh_window_action = None
        coordinator.main_window = FakeMainWindow()
        cached_scene = mesh_publication(
            ("old-vertices", "old-normals", "old-indices", "old-colors"),
            scene_identity(active_ref, 7),
            {"page-1": 7.0},
        )
        configure_mesh_state(
            coordinator,
            last_mesh_scene=cached_scene,
            visualization=FakeVisualization(
                pending_mesh_scene_identity=scene_identity(active_ref, 8)
            ),
        )
        from ost_visualizer.presentation.coordinators import ui_event_coordinator

        original = ui_event_coordinator.MeshViewWindow
        ui_event_coordinator.MeshViewWindow = FakeConstructedMeshWindow
        try:
            coordinator.set_mesh_window_visible(True)
        finally:
            ui_event_coordinator.MeshViewWindow = original
        self.assertEqual(coordinator.visualization_service.mesh_pages, [])
        self.assertEqual(coordinator._mesh_window.mesh_calls, [])
        self.assertEqual(
            coordinator._mesh_window.scene_refreshes,
            [(active_ref, ("page-1",))],
        )
        self.assertIs(coordinator._last_mesh_scene, cached_scene)

    def test_opening_detached_mesh_window_with_stale_cache_requests_fresh_mesh(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        active_ref = BidRef("test.mdb", "bid-1")
        coordinator.ui_state_manager = FakeUiState()
        coordinator.ui_state_manager.get_selected_bid_ref = lambda: active_ref
        coordinator.project_data = FakeProjectData()
        coordinator._icon_provider = None
        coordinator._color_service = None
        coordinator._plan_view_handler = None
        coordinator._mesh_window = None
        coordinator._mesh_window_action = None
        coordinator.main_window = FakeMainWindow()
        configure_mesh_state(
            coordinator,
            last_mesh_scene=mesh_publication(
                ("vertices", "normals", "indices", "colors"),
                scene_identity(active_ref, 7, ("other-page",)),
                {"other-page": 7.0},
            ),
        )
        from ost_visualizer.presentation.coordinators import ui_event_coordinator

        original = ui_event_coordinator.MeshViewWindow
        ui_event_coordinator.MeshViewWindow = FakeConstructedMeshWindow
        try:
            coordinator.set_mesh_window_visible(True)
        finally:
            ui_event_coordinator.MeshViewWindow = original
        self.assertEqual(coordinator.visualization_service.mesh_pages, [["page-1"]])
        self.assertEqual(
            coordinator._mesh_window.scene_refreshes,
            [(active_ref, ("page-1",))],
        )
        self.assertEqual(coordinator._mesh_window.mesh_calls, [])
        self.assertIsNone(coordinator._last_mesh_scene)

    def test_opening_detached_mesh_window_without_cache_requests_fresh_mesh(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        active_ref = BidRef("test.mdb", "bid-1")
        coordinator.ui_state_manager = FakeUiState()
        coordinator.ui_state_manager.get_selected_bid_ref = lambda: active_ref
        coordinator.project_data = FakeProjectData()
        coordinator._icon_provider = None
        coordinator._color_service = None
        coordinator._plan_view_handler = None
        coordinator._mesh_window = None
        coordinator._mesh_window_action = None
        coordinator.main_window = FakeMainWindow()
        configure_mesh_state(coordinator)
        from ost_visualizer.presentation.coordinators import ui_event_coordinator

        original = ui_event_coordinator.MeshViewWindow
        ui_event_coordinator.MeshViewWindow = FakeConstructedMeshWindow
        try:
            coordinator.set_mesh_window_visible(True)
        finally:
            ui_event_coordinator.MeshViewWindow = original
        self.assertEqual(coordinator.visualization_service.mesh_pages, [["page-1"]])
        self.assertEqual(
            coordinator._mesh_window.scene_refreshes,
            [(active_ref, ("page-1",))],
        )
        self.assertEqual(coordinator._mesh_window.mesh_calls, [])

    def test_opening_detached_mesh_window_replaces_mismatched_pending_generation(
        self,
    ):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        active_ref = BidRef("test.mdb", "bid-1")
        coordinator.ui_state_manager = FakeUiState()
        coordinator.ui_state_manager.get_selected_bid_ref = lambda: active_ref
        coordinator.project_data = FakeProjectData()
        coordinator._icon_provider = None
        coordinator._color_service = None
        coordinator._plan_view_handler = None
        coordinator._mesh_window = None
        coordinator._mesh_window_action = None
        coordinator.main_window = FakeMainWindow()
        configure_mesh_state(
            coordinator,
            visualization=FakeVisualization(
                pending_mesh_scene_identity=scene_identity(
                    active_ref, 41, ("other-page",)
                )
            ),
        )
        coordinator._mesh_scene_dirty = True
        coordinator._dirty_mesh_page_uids = {"page-1"}
        coordinator._pending_dirty_mesh_refresh = True
        from ost_visualizer.presentation.coordinators import ui_event_coordinator

        original = ui_event_coordinator.MeshViewWindow
        ui_event_coordinator.MeshViewWindow = FakeConstructedMeshWindow
        try:
            coordinator.set_mesh_window_visible(True)
        finally:
            ui_event_coordinator.MeshViewWindow = original
        self.assertEqual(coordinator.visualization_service.mesh_pages, [["page-1"]])
        self.assertEqual(
            coordinator._mesh_window.scene_refreshes,
            [(active_ref, ("page-1",))],
        )
        self.assertTrue(coordinator._pending_dirty_mesh_refresh)

    def test_detached_mesh_can_reopen_before_old_destroyed_signal_arrives(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = FakeUiState()
        coordinator.project_data = FakeProjectData()
        coordinator._icon_provider = None
        coordinator._color_service = None
        coordinator._plan_view_handler = None
        coordinator._mesh_window = None
        coordinator._mesh_window_action = None
        coordinator._last_mesh_scene = None
        coordinator.ui_access_manager = FakeMeshAccess()
        coordinator.main_window = FakeMainWindow()
        configure_mesh_state(coordinator)
        from ost_visualizer.presentation.coordinators import ui_event_coordinator

        original = ui_event_coordinator.MeshViewWindow
        ui_event_coordinator.MeshViewWindow = FakeConstructedMeshWindow
        try:
            coordinator.set_mesh_window_visible(True)
            old_window = coordinator._mesh_window
            old_destroyed = old_window.destroyed.callbacks[0]
            coordinator.set_mesh_window_visible(False)
            self.assertIsNone(coordinator._mesh_window)
            coordinator.set_mesh_window_visible(True)
            replacement = coordinator._mesh_window
            self.assertIsNot(replacement, old_window)
            old_destroyed(None)
            self.assertIs(coordinator._mesh_window, replacement)
        finally:
            ui_event_coordinator.MeshViewWindow = original

    def test_detached_mesh_opened_during_generation_accepts_pending_scene(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        active_ref = BidRef("test.mdb", "bid-1")
        coordinator.ui_state_manager = FakeUiState()
        coordinator.ui_state_manager.get_selected_bid_ref = lambda: active_ref
        coordinator.project_data = FakeProjectData()
        coordinator._icon_provider = None
        coordinator._color_service = None
        coordinator._plan_view_handler = None
        coordinator._mesh_window = None
        coordinator._mesh_window_action = None
        coordinator._last_mesh_scene = None
        coordinator.ui_access_manager = FakeMeshAccess()
        coordinator.main_window = FakeMainWindow()
        configure_mesh_state(
            coordinator,
            visualization=FakeVisualization(
                pending_mesh_scene_identity=scene_identity(active_ref, 42)
            ),
        )
        coordinator._mesh_scene_dirty = True
        coordinator._dirty_mesh_page_uids = {"page-1"}
        coordinator._pending_dirty_mesh_refresh = True
        coordinator._nav = FakeNav()
        coordinator._plan_view_signaler = FakeMeshPlanSignaler()
        from ost_visualizer.presentation.coordinators import ui_event_coordinator

        original = ui_event_coordinator.MeshViewWindow
        ui_event_coordinator.MeshViewWindow = FakeConstructedMeshWindow
        try:
            coordinator.set_mesh_window_visible(True)
            window = coordinator._mesh_window
            self.assertEqual(
                window.scene_refreshes,
                [(active_ref, ("page-1",))],
            )
            self.assertEqual(coordinator.visualization_service.mesh_pages, [])
            coordinator._on_native_scene_updated(
                geometries=[mesh_geometry("page-1", 17.0)],
                scene_identity=scene_identity(active_ref, 42),
                scene_failed=False,
            )
            self.assertEqual(len(window.mesh_calls), 1)
            self.assertEqual(
                window.mesh_calls[0][1]["page_floor_elevations"],
                {"page-1": 17.0},
            )
        finally:
            ui_event_coordinator.MeshViewWindow = original


class UIEventCoordinatorOnViewStackChangedTests(
    _UIEventCoordinatorTakeoffsChangedFixture
):
    """UIEventCoordinator._on_view_stack_changed."""

    def test_embedded_view_uses_same_validated_replay_path_as_detached_view(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        active_ref = BidRef("test.mdb", "bid-1")
        coordinator.ui_state_manager = FakeUiState()
        coordinator.ui_state_manager.get_selected_bid_ref = lambda: active_ref
        coordinator.project_data = FakeProjectData()
        embedded = FakeMeshReceiver()
        configure_mesh_state(coordinator, view_index=0, opengl_viewer=embedded)
        coordinator._placement = FakePlacement()
        coordinator._toolbar = FakeToolbar()
        coordinator._sidebar = FakeSidebar()
        coordinator.plan_view = None
        coordinator._sync_page_info_status = lambda: None
        publication = mesh_publication(
            ("vertices", "normals", "indices", "colors"),
            scene_identity(active_ref, 7),
            {"page-1": 7.0},
        )
        coordinator._last_mesh_scene = publication
        coordinator._on_view_stack_changed(0)
        self.assertEqual(
            embedded.scene_refreshes,
            [(active_ref, ("page-1",))],
        )
        self.assertEqual(len(embedded.mesh_calls), 1)
        self.assertEqual(
            embedded.mesh_calls[0][1]["scene_identity"], publication.scene_identity
        )
        embedded.scene_refreshes.clear()
        embedded.mesh_calls.clear()
        coordinator._last_mesh_scene = mesh_publication(
            ("vertices", "normals", "indices", "colors"),
            scene_identity(BidRef("test.mdb", "stale-bid"), 8),
            {"page-1": 8.0},
        )
        coordinator._on_view_stack_changed(0)
        self.assertEqual(embedded.scene_refreshes, [])
        self.assertEqual(embedded.mesh_calls, [])
        self.assertIsNone(coordinator._last_mesh_scene)

    def test_view_stack_switch_to_3d_exits_placement_and_syncs_select_action(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)

        class UiState:
            def __init__(self):
                self.place_condition_uid = "c1"

            def clear_place_condition(self):
                self.place_condition_uid = None

        coordinator.ui_state_manager = UiState()
        coordinator._is_cleaning_up = False
        coordinator.plan_view = None
        coordinator._placement = FakePlacement()
        coordinator._placement.is_active = True
        coordinator._toolbar = FakeToolbar()
        coordinator._sidebar = FakeSidebar()
        coordinator._selected_takeoff_uids = ("t1", "t2")
        coordinator._selection_projected_condition_uids = {"c1", "c2"}
        configure_mesh_state(coordinator)
        coordinator._sync_page_info_status = lambda: None
        coordinator._on_view_stack_changed(0)
        self.assertEqual(coordinator._placement.force_exit_count, 1)
        self.assertIsNone(coordinator.ui_state_manager.place_condition_uid)
        self.assertEqual(coordinator._toolbar.select_checked, 1)
        self.assertEqual(coordinator._sidebar.quantity_updates, 1)
        self.assertEqual(coordinator._selected_takeoff_uids, ("t1", "t2"))

    def test_late_view_stack_signal_after_cleanup_is_ignored(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = True
        coordinator._placement = None
        coordinator._toolbar = None
        coordinator._sidebar = None
        coordinator.ui_state_manager = None
        coordinator.plan_view = None
        coordinator._on_view_stack_changed(0)


class UIEventCoordinatorOnNativeSceneUpdatedTests(
    _UIEventCoordinatorTakeoffsChangedFixture
):
    """UIEventCoordinator._on_native_scene_updated."""

    def test_native_scene_update_consumes_mesh_geometry_dtos(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._nav = FakeNav()
        coordinator.ui_access_manager = FakeMeshAccess()
        coordinator.ui_state_manager = FakeUiState()
        coordinator.project_data = FakeProjectData()
        opengl_viewer = FakeMeshReceiver()
        mesh_window = FakeMeshReceiver()
        coordinator._plan_view_signaler = FakeMeshPlanSignaler()
        configure_mesh_state(
            coordinator,
            view_index=0,
            opengl_viewer=opengl_viewer,
            mesh_window=mesh_window,
        )
        coordinator._last_mesh_scene = None
        active_ref = BidRef("test.mdb", "bid-1")
        coordinator.ui_state_manager.get_selected_bid_ref = lambda: active_ref
        geometry = mesh_geometry("page-1", 0.0)
        coordinator._on_native_scene_updated(
            geometries=[geometry],
            scene_identity=scene_identity(active_ref, 7),
            scene_failed=False,
        )
        self.assertEqual(1, len(coordinator.opengl_viewer.mesh_calls))
        args, mesh_options = coordinator.opengl_viewer.mesh_calls[0]
        self.assertEqual(
            (
                [[0.0, 0.0, 2.0, 1.0, 1.0, 0.0]],
                [[0.0, 1.0, 0.0]],
                [[0, 1, 2]],
            ),
            args[:3],
        )
        self.assertEqual([{"color": "#123456", "opacity": 0.75}], args[3])
        self.assertEqual(["condition-1"], mesh_options["condition_uids"])
        self.assertEqual(["takeoff-1"], mesh_options["takeoff_uids"])
        self.assertEqual({"page-1": 0.0}, mesh_options["page_floor_elevations"])
        self.assertEqual(
            coordinator._last_mesh_scene.scene_identity,
            mesh_options["scene_identity"],
        )
        self.assertEqual(mesh_window.mesh_calls, opengl_viewer.mesh_calls)
        self.assertEqual(1, coordinator._plan_view_signaler.requests)

    def test_older_scene_callback_cannot_replace_cached_authoritative_generation(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._nav = FakeNav()
        coordinator.ui_access_manager = FakeMeshAccess()
        coordinator.ui_state_manager = FakeUiState()
        coordinator.project_data = FakeProjectData()
        embedded = FakeMeshReceiver()
        detached = FakeMeshReceiver()
        coordinator._plan_view_signaler = FakeMeshPlanSignaler()
        active_ref = BidRef("test.mdb", "bid-1")
        current_scene = mesh_publication(
            ("new-vertices", "new-normals", "new-indices", "new-colors"),
            scene_identity(active_ref, 12),
            {"page-1": 12.0},
        )
        configure_mesh_state(
            coordinator,
            view_index=0,
            opengl_viewer=embedded,
            mesh_window=detached,
            last_mesh_scene=current_scene,
        )
        coordinator.ui_state_manager.get_selected_bid_ref = lambda: active_ref
        coordinator._on_native_scene_updated(
            geometries=[mesh_geometry("page-1", 7.0)],
            scene_identity=scene_identity(active_ref, 7),
            scene_failed=False,
        )
        self.assertIs(coordinator._last_mesh_scene, current_scene)
        self.assertEqual(embedded.mesh_calls, [])
        self.assertEqual(detached.mesh_calls, [])
        self.assertEqual(coordinator._plan_view_signaler.requests, 0)

    def test_scene_publication_fans_out_page_uid_elevations_identically(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._nav = FakeNav()
        coordinator.ui_access_manager = FakeMeshAccess()
        coordinator.ui_state_manager = FakeUiState()
        coordinator.project_data = FakeProjectData()
        coordinator.project_data.selected_page_uids = ["page-b", "page-a"]
        embedded = FakeMeshReceiver()
        detached = FakeMeshReceiver()
        coordinator._plan_view_signaler = FakeMeshPlanSignaler()
        configure_mesh_state(
            coordinator,
            view_index=0,
            opengl_viewer=embedded,
            mesh_window=detached,
        )
        active_ref = BidRef("test.mdb", "bid-1")
        coordinator.ui_state_manager.get_selected_bid_ref = lambda: active_ref
        coordinator._on_native_scene_updated(
            geometries=[
                mesh_geometry("page-b", 25.0, "takeoff-b"),
                mesh_geometry("page-a", 10.0, "takeoff-a"),
            ],
            scene_identity=scene_identity(
                active_ref,
                8,
                ("page-b", "page-a"),
            ),
            scene_failed=False,
        )
        expected = {"page-a": 10.0, "page-b": 25.0}
        self.assertEqual(
            embedded.mesh_calls[0][1]["page_floor_elevations"],
            expected,
        )
        self.assertEqual(
            detached.mesh_calls[0][1]["page_floor_elevations"],
            expected,
        )
        self.assertEqual(
            coordinator._last_mesh_scene.page_floor_elevations,
            expected,
        )
        with self.assertRaises(TypeError):
            coordinator._last_mesh_scene.page_floor_elevations["page-a"] = -100.0

    def test_native_scene_update_rejects_stale_bid_before_touching_views(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._nav = FakeNav()
        coordinator.ui_access_manager = FakeMeshAccess()
        coordinator.ui_state_manager = FakeUiState()
        active_ref = BidRef("active.mdb", "active-bid")
        coordinator.ui_state_manager.get_selected_bid_ref = lambda: active_ref
        coordinator.project_data = FakeProjectData()
        opengl_viewer = FakeMeshReceiver()
        mesh_window = FakeMeshReceiver()
        coordinator._plan_view_signaler = FakeMeshPlanSignaler()
        configure_mesh_state(
            coordinator,
            view_index=0,
            opengl_viewer=opengl_viewer,
            mesh_window=mesh_window,
        )
        coordinator._last_mesh_scene = None
        coordinator._on_native_scene_updated(
            geometries=[],
            scene_identity=scene_identity(BidRef("stale.mdb", "stale-bid"), 21),
            scene_failed=False,
        )
        self.assertEqual(opengl_viewer.mesh_calls, [])
        self.assertEqual(mesh_window.mesh_calls, [])
        self.assertIsNone(coordinator._last_mesh_scene)


class UIEventCoordinatorSyncSelectionTests(_UIEventCoordinatorTakeoffsChangedFixture):
    """UIEventCoordinator._sync_selection."""

    def test_2d_and_3d_multi_selection_share_one_condition_projection(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)

        class UiState:
            def __init__(self):
                self.highlighted_condition_uids = set()

            def set_highlighted_conditions(self, uids):
                self.highlighted_condition_uids = set(uids)

        class ProjectData:
            def get_all_takeoffs(self):
                return [
                    type(
                        "Takeoff",
                        (),
                        {"uid": "t1", "condition_uid": "c1", "visible": True},
                    )(),
                    type(
                        "Takeoff",
                        (),
                        {"uid": "t2", "condition_uid": "c1", "visible": True},
                    )(),
                    type(
                        "Takeoff",
                        (),
                        {"uid": "t3", "condition_uid": "c2", "visible": False},
                    )(),
                ]

        class Sidebar:
            def __init__(self):
                self.highlights = []
                self.selected = set()

            def highlight_conditions(self, uids, reveal=True):
                self.selected = set(uids)
                self.highlights.append(set(uids))

            def get_selected_condition_uids(self):
                return sorted(self.selected)

        class PlanView:
            def __init__(self):
                self.selected = set()

            def set_selected_uids(self, uids, emit=True):
                self.selected = set(uids)

            def clear_selection(self, emit=True):
                self.selected = set()

        class MeshView:
            def __init__(self):
                self.selected = []

            def set_selected_takeoffs(self, uids):
                self.selected = list(uids)

        coordinator.ui_state_manager = UiState()
        coordinator.project_data = ProjectData()
        coordinator.conditions_sidebar = Sidebar()
        coordinator.plan_view = PlanView()
        coordinator.opengl_viewer = MeshView()
        coordinator._mesh_window = MeshView()
        coordinator._placement = FakePlacement()
        coordinator._toolbar = FakeToolbar()
        coordinator._tab_widget = FakeTabWidget(index=1)
        coordinator._nav = type("Nav", (), {"is_refreshing": False})()
        coordinator._selected_takeoff_uids = ()
        coordinator._selection_projected_condition_uids = set()
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1"])
        self.assertEqual(
            coordinator.ui_state_manager.highlighted_condition_uids, {"c1"}
        )
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1", "t2"])
        self.assertEqual(
            coordinator.ui_state_manager.highlighted_condition_uids, {"c1"}
        )
        self.assertEqual(coordinator.opengl_viewer.selected, ["t1", "t2"])
        self.assertEqual(coordinator._mesh_window.selected, ["t1", "t2"])
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1", "t3"])
        self.assertEqual(
            coordinator.ui_state_manager.highlighted_condition_uids, {"c1", "c2"}
        )
        coordinator._sync_selection(coordinator._SOURCE_3D, ["t1"])
        self.assertEqual(
            coordinator.ui_state_manager.highlighted_condition_uids, {"c1"}
        )
        coordinator._sync_selection(coordinator._SOURCE_3D, ["t1", "t2"])
        self.assertEqual(
            coordinator.ui_state_manager.highlighted_condition_uids, {"c1"}
        )
        coordinator._sync_selection(coordinator._SOURCE_3D, ["t1", "t1", "t3"])
        self.assertEqual(
            coordinator.ui_state_manager.highlighted_condition_uids, {"c1", "c2"}
        )
        self.assertEqual(coordinator.plan_view.selected, {"t1", "t3"})
        self.assertEqual(coordinator._mesh_window.selected, ["t1", "t3"])
        highlight_count = len(coordinator.conditions_sidebar.highlights)
        coordinator._sync_selection(coordinator._SOURCE_3D, ["t1", "t3"])
        self.assertEqual(
            len(coordinator.conditions_sidebar.highlights), highlight_count
        )
        # A passive sidebar projection may temporarily retain only one row. A
        # duplicate user selection must restore the complete canonical set.
        coordinator.ui_state_manager.set_highlighted_conditions({"c1"})
        coordinator._sync_selection(coordinator._SOURCE_3D, ["t1", "t3"])
        self.assertEqual(
            coordinator.ui_state_manager.highlighted_condition_uids, {"c1", "c2"}
        )
        coordinator._sync_selection(coordinator._SOURCE_3D, ["t3"])
        self.assertEqual(
            coordinator.ui_state_manager.highlighted_condition_uids, {"c2"}
        )
        coordinator._sync_selection(coordinator._SOURCE_3D, [])
        self.assertEqual(coordinator.ui_state_manager.highlighted_condition_uids, set())
        self.assertEqual(coordinator.plan_view.selected, set())
        self.assertEqual(coordinator._mesh_window.selected, [])
        self.assertEqual(
            coordinator.conditions_sidebar.highlights,
            [
                {"c1"},
                {"c1", "c2"},
                {"c1"},
                {"c1", "c2"},
                {"c1", "c2"},
                {"c2"},
                set(),
            ],
        )

    def test_clearing_takeoff_selection_clears_takeoff_owned_condition(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)

        class UiState:
            def __init__(self):
                self.highlighted_condition_uids = set()

            def set_highlighted_conditions(self, uids):
                self.highlighted_condition_uids = set(uids)

        class ProjectData:
            def get_all_takeoffs(self):
                return [type("Takeoff", (), {"uid": "t1", "condition_uid": "c1"})()]

        class Sidebar:
            def __init__(self):
                self.highlights = []
                self.selected = set()

            def highlight_conditions(self, uids, reveal=True):
                self.selected = set(uids)
                self.highlights.append(set(uids))

            def get_selected_condition_uids(self):
                return sorted(self.selected)

        coordinator.ui_state_manager = UiState()
        coordinator.project_data = ProjectData()
        coordinator.conditions_sidebar = Sidebar()
        coordinator.plan_view = None
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator._placement = FakePlacement()
        coordinator._toolbar = FakeToolbar()
        coordinator._tab_widget = FakeTabWidget(index=1)
        coordinator._nav = type("Nav", (), {"is_refreshing": False})()
        coordinator._selected_takeoff_uids = ()
        coordinator._selection_projected_condition_uids = set()
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1"])
        coordinator._sync_selection(coordinator._SOURCE_2D, [])
        self.assertEqual(coordinator.ui_state_manager.highlighted_condition_uids, set())
        self.assertEqual(coordinator.conditions_sidebar.highlights, [{"c1"}, set()])

    def test_repeated_takeoff_selection_sync_does_not_override_dialog_condition(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)

        class UiState:
            def __init__(self):
                self.highlighted_condition_uids = set()

            def set_highlighted_conditions(self, uids):
                self.highlighted_condition_uids = set(uids)

        class ProjectData:
            def get_all_takeoffs(self):
                return [type("Takeoff", (), {"uid": "t1", "condition_uid": "c1"})()]

        class Sidebar:
            def __init__(self):
                self.highlights = []
                self.selected = set()

            def highlight_conditions(self, uids, reveal=True):
                self.selected = set(uids)
                self.highlights.append(set(uids))

            def get_selected_condition_uids(self):
                return sorted(self.selected)

        coordinator.ui_state_manager = UiState()
        coordinator.project_data = ProjectData()
        coordinator.conditions_sidebar = Sidebar()
        coordinator.plan_view = None
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator._placement = FakePlacement()
        coordinator._toolbar = FakeToolbar()
        coordinator._tab_widget = FakeTabWidget(index=1)
        coordinator._nav = type("Nav", (), {"is_refreshing": False})()
        coordinator._selected_takeoff_uids = ()
        coordinator._selection_projected_condition_uids = set()
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1"])
        coordinator.highlight_sidebar({"c2"})
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1"])
        self.assertEqual(
            coordinator.ui_state_manager.highlighted_condition_uids, {"c2"}
        )
        self.assertEqual(coordinator.conditions_sidebar.highlights, [{"c1"}, {"c2"}])

    def test_same_bid_refresh_does_not_restore_original_condition_after_duplicate(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)

        class UiState:
            def __init__(self):
                self.highlighted_condition_uids = set()

            def set_highlighted_conditions(self, uids):
                self.highlighted_condition_uids = set(uids)

        class ProjectData:
            def get_all_takeoffs(self):
                return [type("Takeoff", (), {"uid": "t1", "condition_uid": "c1"})()]

        class Sidebar:
            def __init__(self):
                self.highlights = []
                self.selected = set()

            def highlight_conditions(self, uids, reveal=True):
                self.selected = set(uids)
                self.highlights.append(set(uids))

            def get_selected_condition_uids(self):
                return sorted(self.selected)

        coordinator.ui_state_manager = UiState()
        coordinator.project_data = ProjectData()
        coordinator.conditions_sidebar = Sidebar()
        coordinator.plan_view = None
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator._placement = FakePlacement()
        coordinator._toolbar = FakeToolbar()
        coordinator._tab_widget = FakeTabWidget(index=1)
        coordinator._nav = type("Nav", (), {"is_refreshing": False})()
        sidebar_clears = []
        coordinator._sidebar = SimpleNamespace(
            clear_sidebars=lambda: sidebar_clears.append(True)
        )
        coordinator._page_settings_bar = None
        coordinator._takeoff_workspace_bid_ref = BidRef("db.mdb", "bid-1")
        coordinator._pending_takeoff_page_uids = None
        coordinator._pending_takeoff_active_page_uid = None
        coordinator._pending_takeoff_selected_area_uid = ""
        coordinator._pending_takeoff_place_condition_uid = None
        coordinator._pending_takeoff_place_condition_uids = []
        coordinator._selected_takeoff_uids = ()
        coordinator._selection_projected_condition_uids = set()
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1"])
        coordinator._reset_takeoff_workspace_state(clear_sidebars=False)
        coordinator.highlight_sidebar({"c2"})
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1"])
        self.assertEqual(
            coordinator.ui_state_manager.highlighted_condition_uids, {"c2"}
        )
        self.assertEqual(coordinator.conditions_sidebar.highlights, [{"c1"}, {"c2"}])
        self.assertEqual(sidebar_clears, [])
        coordinator._reset_takeoff_workspace_state(clear_sidebars=True)
        self.assertEqual(coordinator._selected_takeoff_uids, ())
        self.assertEqual(coordinator._selection_projected_condition_uids, set())
        self.assertEqual(sidebar_clears, [True])

    def test_repeated_takeoff_click_restores_highlight_after_reload_clears_it(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)

        class UiState:
            def __init__(self):
                self.highlighted_condition_uids = set()

            def set_highlighted_conditions(self, uids):
                self.highlighted_condition_uids = set(uids)

        class ProjectData:
            def get_all_takeoffs(self):
                return [type("Takeoff", (), {"uid": "t1", "condition_uid": "c1"})()]

        class Sidebar:
            def __init__(self):
                self.highlights = []
                self.selected = set()

            def highlight_conditions(self, uids, reveal=True):
                self.selected = set(uids)
                self.highlights.append(set(uids))

            def get_selected_condition_uids(self):
                return sorted(self.selected)

        coordinator.ui_state_manager = UiState()
        coordinator.project_data = ProjectData()
        coordinator.conditions_sidebar = Sidebar()
        coordinator.plan_view = None
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator._placement = FakePlacement()
        coordinator._toolbar = FakeToolbar()
        coordinator._tab_widget = FakeTabWidget(index=1)
        coordinator._nav = type("Nav", (), {"is_refreshing": False})()
        coordinator._selected_takeoff_uids = ()
        coordinator._selection_projected_condition_uids = set()
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1"])
        coordinator.ui_state_manager.set_highlighted_conditions(set())
        coordinator.conditions_sidebar.highlights.clear()
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1"])
        self.assertEqual(
            coordinator.ui_state_manager.highlighted_condition_uids, {"c1"}
        )
        self.assertEqual(coordinator.conditions_sidebar.highlights, [{"c1"}])

    def test_each_takeoff_source_repairs_incomplete_owned_sidebar_projection(self):
        class UiState:
            def __init__(self):
                self.highlighted_condition_uids = set()

            def set_highlighted_conditions(self, uids):
                self.highlighted_condition_uids = set(uids)

        class ProjectData:
            def get_all_takeoffs(self):
                return [
                    type("Takeoff", (), {"uid": "t1", "condition_uid": "c1"})(),
                    type("Takeoff", (), {"uid": "t2", "condition_uid": "c2"})(),
                ]

        class Sidebar:
            def __init__(self):
                self.highlights = []
                self.selected = set()

            def highlight_conditions(self, uids, reveal=True):
                self.selected = set(uids)
                self.highlights.append(set(uids))

            def get_selected_condition_uids(self):
                return sorted(self.selected)

        for source in (
            UIEventCoordinator._SOURCE_2D,
            UIEventCoordinator._SOURCE_3D,
            UIEventCoordinator._SOURCE_3D_WINDOW,
        ):
            with self.subTest(source=source):
                coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
                coordinator.ui_state_manager = UiState()
                coordinator.project_data = ProjectData()
                coordinator.conditions_sidebar = Sidebar()
                coordinator.plan_view = None
                coordinator.opengl_viewer = None
                coordinator._mesh_window = None
                coordinator._placement = FakePlacement()
                coordinator._placement.is_active = True
                coordinator._placement.condition_uid = "c2"
                coordinator._toolbar = FakeToolbar()
                coordinator._tab_widget = FakeTabWidget(index=1)
                coordinator._nav = type("Nav", (), {"is_refreshing": False})()
                coordinator._selected_takeoff_uids = ()
                coordinator._selection_projected_condition_uids = set()
                coordinator._sync_selection(source, ["t2", "t1", "t2"])
                self.assertEqual(coordinator._selected_takeoff_uids, ("t1", "t2"))
                self.assertEqual(
                    coordinator.ui_state_manager.highlighted_condition_uids,
                    {"c1", "c2"},
                )
                coordinator.conditions_sidebar.selected = {"c1"}
                projected_count = len(coordinator.conditions_sidebar.highlights)
                coordinator._sync_selection(source, ["t1", "t2"])
                self.assertEqual(
                    coordinator.ui_state_manager.highlighted_condition_uids,
                    {"c1", "c2"},
                )
                self.assertEqual(coordinator.conditions_sidebar.selected, {"c1", "c2"})
                self.assertEqual(
                    len(coordinator.conditions_sidebar.highlights),
                    projected_count + 1,
                )
                coordinator._sync_selection(source, ["t1", "t2"])
                self.assertEqual(
                    len(coordinator.conditions_sidebar.highlights),
                    projected_count + 1,
                )
                coordinator._sync_selection(source, ["t1"])
                self.assertEqual(coordinator._placement.enter_calls, [])

    def test_takeoff_projection_deferred_during_refresh_repairs_when_idle(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)

        class UiState:
            highlighted_condition_uids = {"c2"}

            def set_highlighted_conditions(self, uids):
                self.highlighted_condition_uids = set(uids)

        class Sidebar:
            def __init__(self):
                self.highlights = []
                self.selected = {"c2"}

            def highlight_conditions(self, uids, reveal=True):
                self.selected = set(uids)
                self.highlights.append(set(uids))

            def get_selected_condition_uids(self):
                return sorted(self.selected)

        coordinator.ui_state_manager = UiState()
        coordinator.project_data = SimpleNamespace(
            get_all_takeoffs=lambda: [
                type("Takeoff", (), {"uid": "t1", "condition_uid": "c1"})()
            ]
        )
        coordinator.conditions_sidebar = Sidebar()
        coordinator.plan_view = None
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator._placement = FakePlacement()
        coordinator._toolbar = FakeToolbar()
        coordinator._tab_widget = FakeTabWidget(index=1)
        coordinator._nav = SimpleNamespace(is_refreshing=True)
        coordinator._selected_takeoff_uids = ()
        coordinator._selection_projected_condition_uids = set()
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1"])
        self.assertEqual(coordinator.conditions_sidebar.selected, {"c2"})
        self.assertEqual(coordinator._selection_projected_condition_uids, {"c1"})
        coordinator._nav.is_refreshing = False
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1"])
        self.assertEqual(coordinator.conditions_sidebar.selected, {"c1"})
        self.assertEqual(
            coordinator.ui_state_manager.highlighted_condition_uids, {"c1"}
        )

    def test_new_takeoff_selection_after_dialog_condition_still_updates_condition(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)

        class UiState:
            def __init__(self):
                self.highlighted_condition_uids = set()

            def set_highlighted_conditions(self, uids):
                self.highlighted_condition_uids = set(uids)

        class ProjectData:
            def get_all_takeoffs(self):
                return [
                    type("Takeoff", (), {"uid": "t1", "condition_uid": "c1"})(),
                    type("Takeoff", (), {"uid": "t2", "condition_uid": "c3"})(),
                ]

        class Sidebar:
            def __init__(self):
                self.highlights = []
                self.selected = set()

            def highlight_conditions(self, uids, reveal=True):
                self.selected = set(uids)
                self.highlights.append(set(uids))

            def get_selected_condition_uids(self):
                return sorted(self.selected)

        coordinator.ui_state_manager = UiState()
        coordinator.project_data = ProjectData()
        coordinator.conditions_sidebar = Sidebar()
        coordinator.plan_view = None
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator._placement = FakePlacement()
        coordinator._toolbar = FakeToolbar()
        coordinator._tab_widget = FakeTabWidget(index=1)
        coordinator._nav = type("Nav", (), {"is_refreshing": False})()
        coordinator._selected_takeoff_uids = ()
        coordinator._selection_projected_condition_uids = set()
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1"])
        coordinator.highlight_sidebar({"c2"})
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t2"])
        self.assertEqual(
            coordinator.ui_state_manager.highlighted_condition_uids, {"c3"}
        )
        self.assertEqual(
            coordinator.conditions_sidebar.highlights, [{"c1"}, {"c2"}, {"c3"}]
        )

    def test_clearing_takeoff_selection_keeps_placement_owned_highlight(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)

        class UiState:
            def __init__(self):
                self.highlighted_condition_uids = set()

            def set_highlighted_conditions(self, uids):
                self.highlighted_condition_uids = set(uids)

        class ProjectData:
            def get_all_takeoffs(self):
                return [type("Takeoff", (), {"uid": "t1", "condition_uid": "c1"})()]

        coordinator.ui_state_manager = UiState()
        coordinator.project_data = ProjectData()
        coordinator.conditions_sidebar = None
        coordinator.plan_view = None
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator._placement = FakePlacement()
        coordinator._placement.is_active = True
        coordinator._placement.condition_uid = "c1"
        coordinator._toolbar = FakeToolbar()
        coordinator._tab_widget = FakeTabWidget(index=1)
        coordinator._nav = type("Nav", (), {"is_refreshing": False})()
        coordinator._selected_takeoff_uids = ()
        coordinator._selection_projected_condition_uids = set()
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1"])
        coordinator._sync_selection(coordinator._SOURCE_2D, [])
        self.assertEqual(
            coordinator.ui_state_manager.highlighted_condition_uids, {"c1"}
        )


class UIEventCoordinatorSelectOverlayImageTests(
    _UIEventCoordinatorTakeoffsChangedFixture
):
    """UIEventCoordinator.select_overlay_image."""

    def test_overlay_file_dialog_cannot_write_to_a_recreated_page_identity(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        bid_ref = BidRef("sql-database", "8")
        original_page = Page(uid="page-1", name="Original")
        replacement_page = Page(uid="page-1", name="Replacement")
        current_page = [original_page]
        saved = []
        coordinator._is_cleaning_up = False
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-1",
            get_selected_bid_ref=lambda: bid_ref,
        )
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        coordinator.project_data = SimpleNamespace(
            get_page=lambda _page_uid: current_page[0]
        )
        coordinator.main_window = object()
        coordinator._save_page_overlay_image = (
            lambda database_id, page_uid, path: saved.append(
                (database_id, page_uid, path)
            )
        )

        def replace_page_while_dialog_is_open(_parent, _current_path):
            current_page[0] = replacement_page
            return "replacement-overlay.pdf"

        with (
            patch(
                "ost_visualizer.presentation.coordinators.ui_event_coordinator."
                "select_overlay_image_path",
                side_effect=replace_page_while_dialog_is_open,
            ),
            patch(
                "ost_visualizer.presentation.coordinators.ui_event_coordinator."
                "show_warning"
            ) as warning,
        ):
            coordinator.select_overlay_image()
        self.assertEqual(saved, [])
        warning.assert_called_once()

    def test_overlay_file_dialog_cannot_write_after_bid_switch(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        original_bid_ref = BidRef("sql-database", "8")
        selected_bid_ref = [original_bid_ref]
        page = Page(uid="page-1", name="Original")
        saved = []
        coordinator._is_cleaning_up = False
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-1",
            get_selected_bid_ref=lambda: selected_bid_ref[0],
        )
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        coordinator.project_data = SimpleNamespace(get_page=lambda _page_uid: page)
        coordinator.main_window = object()
        coordinator._save_page_overlay_image = (
            lambda database_id, page_uid, path: saved.append(
                (database_id, page_uid, path)
            )
        )

        def switch_bid_while_dialog_is_open(_parent, _current_path):
            selected_bid_ref[0] = BidRef("sql-database", "9")
            return "replacement-overlay.pdf"

        with (
            patch(
                "ost_visualizer.presentation.coordinators.ui_event_coordinator."
                "select_overlay_image_path",
                side_effect=switch_bid_while_dialog_is_open,
            ),
            patch(
                "ost_visualizer.presentation.coordinators.ui_event_coordinator."
                "show_warning"
            ) as warning,
        ):
            coordinator.select_overlay_image()
        self.assertEqual(saved, [])
        warning.assert_called_once()

    def test_overlay_file_dialog_cannot_write_after_access_revocation(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        bid_ref = BidRef("sql-database", "8")
        page = Page(uid="page-1", name="Original")
        access_allowed = [True]
        saved = []
        coordinator._is_cleaning_up = False
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-1",
            get_selected_bid_ref=lambda: bid_ref,
        )
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: access_allowed[0]
        )
        coordinator.project_data = SimpleNamespace(get_page=lambda _page_uid: page)
        coordinator.main_window = object()
        coordinator._save_page_overlay_image = (
            lambda database_id, page_uid, path: saved.append(
                (database_id, page_uid, path)
            )
        )

        def revoke_access_while_dialog_is_open(_parent, _current_path):
            access_allowed[0] = False
            return "replacement-overlay.pdf"

        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator."
            "select_overlay_image_path",
            side_effect=revoke_access_while_dialog_is_open,
        ):
            coordinator.select_overlay_image()
        self.assertEqual(saved, [])

    def test_overlay_file_dialog_return_after_cleanup_is_ignored(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        bid_ref = BidRef("sql-database", "8")
        page = Page(uid="page-1", name="Original")
        saved = []
        coordinator._is_cleaning_up = False
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-1",
            get_selected_bid_ref=lambda: bid_ref,
        )
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        coordinator.project_data = SimpleNamespace(get_page=lambda _page_uid: page)
        coordinator.main_window = object()
        coordinator._save_page_overlay_image = (
            lambda database_id, page_uid, path: saved.append(
                (database_id, page_uid, path)
            )
        )

        def finish_cleanup_while_dialog_is_open(_parent, _current_path):
            coordinator._is_cleaning_up = True
            return "replacement-overlay.pdf"

        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator."
            "select_overlay_image_path",
            side_effect=finish_cleanup_while_dialog_is_open,
        ):
            coordinator.select_overlay_image()
        self.assertEqual(saved, [])

    def test_overlay_file_dialog_return_after_window_destruction_is_ignored(self):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        bid_ref = BidRef("sql-database", "8")
        page = Page(uid="page-1", name="Original")
        saved = []
        window = QtWidgets.QWidget()
        coordinator._is_cleaning_up = False
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-1",
            get_selected_bid_ref=lambda: bid_ref,
        )
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        coordinator.project_data = SimpleNamespace(get_page=lambda _page_uid: page)
        coordinator.main_window = window
        coordinator._save_page_overlay_image = (
            lambda database_id, page_uid, path: saved.append(
                (database_id, page_uid, path)
            )
        )

        def destroy_window_while_dialog_is_open(_parent, _current_path):
            delete(window)
            return "replacement-overlay.pdf"

        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator."
            "select_overlay_image_path",
            side_effect=destroy_window_while_dialog_is_open,
        ):
            coordinator.select_overlay_image()
        self.assertEqual(saved, [])
        app.processEvents()


class UIEventCoordinatorHandleBidSelectionTests(
    _UIEventCoordinatorTakeoffsChangedFixture
):
    """UIEventCoordinator.handle_bid_selection."""

    def test_completed_background_bid_load_clears_loading_status_on_projects_tab(self):
        coordinator = navigation_status_coordinator()
        coordinator.handle_bid_selection(BidRef("sql-database", "bid-1"))
        self.assertEqual(coordinator._status_panel.page_info, "Loading bid pages…")
        coordinator.project_operations.complete(True)
        self.assertEqual(coordinator._status_panel.page_info, "")

    def test_sql_bid_load_from_no_file_projects_bid_base_without_warning(self):
        coordinator = navigation_status_coordinator()
        coordinator._nav = NavigationStateMachine()
        logger = "ost_visualizer.presentation.coordinators.navigation_state_machine"
        with self.assertNoLogs(logger, level="WARNING"):
            coordinator.handle_bid_selection(BidRef("sql-database", "bid-1"))
            self.assertEqual(
                coordinator._nav.current_state, NavState.FILE_LOADED_NO_BID
            )
            coordinator.project_operations.complete(True)
        self.assertEqual(coordinator._nav.current_state, NavState.BID_ACTIVE_NO_PAGES)

    def test_slow_sql_bid_switch_keeps_old_state_until_accepted_completion(self):
        coordinator = navigation_status_coordinator()
        coordinator._nav = NavigationStateMachine()
        coordinator._nav.transition_to(NavState.FILE_LOADED_NO_BID)
        coordinator._nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)
        coordinator._nav.transition_to(NavState.BID_ACTIVE_PAGES_SELECTED)
        coordinator.ui_state_manager.bid_ref = BidRef("sql-database", "old-bid")
        logger = "ost_visualizer.presentation.coordinators.navigation_state_machine"
        with self.assertNoLogs(logger, level="WARNING"):
            coordinator.handle_bid_selection(BidRef("sql-database", "new-bid"))
            self.assertEqual(
                coordinator._nav.current_state,
                NavState.BID_ACTIVE_PAGES_SELECTED,
            )
            coordinator.project_operations.complete(True)
        self.assertEqual(coordinator._nav.current_state, NavState.BID_ACTIVE_NO_PAGES)

    def test_bid_switch_flushes_deferred_writes_under_originating_bid(self):
        coordinator = navigation_status_coordinator()
        old_ref = BidRef("sql-database", "old-bid")
        new_ref = BidRef("sql-database", "new-bid")
        coordinator.ui_state_manager.bid_ref = old_ref
        sequence = []
        coordinator._save_current_page_view_state = lambda: sequence.append(
            ("save", coordinator.ui_state_manager.get_selected_bid_ref())
        )
        coordinator._flush_deferred_for_file = (
            lambda file_path: sequence.append(
                (
                    "flush",
                    file_path,
                    coordinator.ui_state_manager.get_selected_bid_ref(),
                )
            )
            or True
        )
        coordinator.project_operations.request_load_bid = (
            lambda bid_ref, _completion: sequence.append(("load", bid_ref)) or True
        )
        coordinator.handle_bid_selection(new_ref)
        self.assertEqual(
            sequence,
            [
                ("save", old_ref),
                ("flush", old_ref.file_path, old_ref),
                ("load", new_ref),
            ],
        )

    def test_failed_deferred_flush_keeps_originating_bid_active(self):
        coordinator = navigation_status_coordinator()
        old_ref = BidRef("sql-database", "old-bid")
        new_ref = BidRef("sql-database", "new-bid")
        coordinator.ui_state_manager.bid_ref = old_ref
        coordinator._flush_deferred_for_file = lambda _file_path: False
        coordinator.handle_bid_selection(new_ref)
        self.assertEqual(coordinator.ui_state_manager.get_selected_bid_ref(), old_ref)
        self.assertFalse(coordinator.project_operations.navigation_load_in_progress())

    def test_mdb_bid_load_from_no_file_projects_bid_base_without_warning(self):
        coordinator = navigation_status_coordinator()
        coordinator.project_data.current_file_path = "project.mdb"
        coordinator.project_operations = ImmediateNavigationOperations()
        coordinator.project_operations.load_bid = lambda _bid_ref: True
        coordinator._nav = NavigationStateMachine()
        logger = "ost_visualizer.presentation.coordinators.navigation_state_machine"
        with self.assertNoLogs(logger, level="WARNING"):
            coordinator.handle_bid_selection(BidRef("project.mdb", "bid-1"))
        self.assertEqual(coordinator._nav.current_state, NavState.BID_ACTIVE_NO_PAGES)

    def test_failed_background_bid_load_clears_loading_status(self):
        coordinator = navigation_status_coordinator()
        coordinator.handle_bid_selection(BidRef("sql-database", "bid-1"))
        self.assertEqual(coordinator._status_panel.page_info, "Loading bid pages…")
        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator.show_warning"
        ) as warning:
            coordinator.project_operations.complete(False, "Schema mismatch")
        warning.assert_called_once_with(
            coordinator.main_window,
            "Open SQL Bid",
            "Schema mismatch",
        )
        self.assertEqual(coordinator._status_panel.page_info, "")

    def test_loading_and_page_status_remain_consistent_while_switching_tabs(self):
        coordinator = navigation_status_coordinator()
        coordinator._status_panel.set_collaboration_state("healthy", "Connected")
        coordinator.handle_bid_selection(BidRef("sql-database", "bid-1"))
        for tab_index in (TAB_INDEX_SUMMARY, TAB_INDEX_PROJECTS, TAB_INDEX_TAKEOFF):
            coordinator._tab_widget.setCurrentIndex(tab_index)
            coordinator._on_tab_changed(tab_index)
            self.assertEqual(
                coordinator._status_panel.page_info,
                "Loading bid pages…",
            )
        self.assertEqual(
            coordinator._status_panel.states,
            [("healthy", "Connected")],
        )
        coordinator._tab_widget.setCurrentIndex(TAB_INDEX_PROJECTS)
        coordinator.project_operations.complete(True)
        self.assertEqual(coordinator._status_panel.page_info, "")
        connection_states_after_load = list(coordinator._status_panel.states)
        coordinator.ui_state_manager.selected_page_uids = ["page-1"]
        coordinator.ui_state_manager.active_page_uid = "page-1"
        for tab_index in (TAB_INDEX_TAKEOFF, TAB_INDEX_SUMMARY):
            coordinator._tab_widget.setCurrentIndex(tab_index)
            coordinator._on_tab_changed(tab_index)
            self.assertEqual(coordinator._status_panel.page_info, "Page One")
        coordinator._tab_widget.setCurrentIndex(TAB_INDEX_PROJECTS)
        coordinator._on_tab_changed(TAB_INDEX_PROJECTS)
        self.assertEqual(coordinator._status_panel.page_info, "")
        self.assertEqual(
            coordinator._status_panel.states,
            connection_states_after_load,
        )

    def test_cancelling_bid_load_clears_loading_status(self):
        coordinator = navigation_status_coordinator()
        coordinator.handle_bid_selection(BidRef("sql-database", "bid-1"))
        self.assertEqual(coordinator._status_panel.page_info, "Loading bid pages…")
        coordinator.handle_bid_selection(None)
        self.assertFalse(coordinator.project_operations.navigation_load_in_progress())
        self.assertEqual(coordinator._status_panel.page_info, "")

    def test_late_empty_tree_selection_after_unload_cannot_restore_file_state(self):
        coordinator = navigation_status_coordinator()
        coordinator.project_data.current_file_path = None
        coordinator._nav = NavigationStateMachine()
        logger = "ost_visualizer.presentation.coordinators.navigation_state_machine"
        with self.assertNoLogs(logger, level="WARNING"):
            coordinator.handle_bid_selection(None)
        self.assertEqual(coordinator._nav.current_state, NavState.NO_FILE)

    def test_synchronous_mdb_bid_load_never_leaves_loading_status(self):
        coordinator = navigation_status_coordinator(tab_index=TAB_INDEX_PROJECTS)
        operations = ImmediateNavigationOperations()
        operations.load_bid = lambda _bid_ref: True
        coordinator.project_operations = operations
        coordinator.handle_bid_selection(BidRef("project.mdb", "bid-1"))
        self.assertNotIn(
            "Loading bid pages…",
            coordinator._status_panel.page_info_states,
        )
        self.assertEqual(coordinator._status_panel.page_info, "")

    def test_selecting_database_while_bid_load_is_pending_clears_loading_status(self):
        coordinator = navigation_status_coordinator()
        coordinator.handle_bid_selection(BidRef("sql-database", "bid-1"))
        self.assertEqual(coordinator._status_panel.page_info, "Loading bid pages…")
        coordinator._on_file_selected(
            file_path="other-sql-database",
            is_database_root=True,
        )
        self.assertFalse(coordinator.project_operations.navigation_load_in_progress())
        self.assertEqual(coordinator._status_panel.page_info, "")

    def test_failed_bid_switch_preserves_old_selection_and_undo_owner(self):
        old_ref = type("BidRefLike", (), {})()
        old_ref.file_path = "old.mdb"
        old_ref.bid_uid = "old-bid"
        new_ref = type("BidRefLike", (), {})()
        new_ref.file_path = "new.mdb"
        new_ref.bid_uid = "new-bid"

        class UiState:
            def __init__(self):
                self.bid_ref = old_ref
                self.page_selection = ["page-1"]

            def get_selected_bid_ref(self):
                return self.bid_ref

            def set_bid_selection(self, bid_ref):
                self.bid_ref = bid_ref

            def set_database_selected(self, *_args):
                pass

            def set_file_path(self, *_args):
                pass

            def set_page_selection(self, page_uids):
                self.page_selection = list(page_uids)

        class ProjectData:
            def __init__(self):
                self.current_file = "old.mdb"
                self.deselects = 0

            def get_current_file_path(self):
                return self.current_file

            def set_current_file(self, file_path):
                self.current_file = file_path

            def deselect_pages(self):
                self.deselects += 1

        class ProjectOperations(ImmediateNavigationOperations):
            def load_bid(self, bid_ref):
                self.requested = bid_ref
                return False

        class Undo:
            def __init__(self):
                self.active = []

            def set_active_bid(self, bid_ref):
                self.active.append(bid_ref)

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.main_window = FakeUnloadMainWindow()
        coordinator._sql_collaboration = FakeSqlCollaboration()
        coordinator._plan_view_handler = None
        coordinator._status_panel = None
        coordinator.main_window.project_view.selected_node = {
            "kind": "bid",
            "file_path": new_ref.file_path,
            "bid_uid": new_ref.bid_uid,
        }
        coordinator.ui_state_manager = UiState()
        coordinator.project_data = ProjectData()
        coordinator.project_operations = ProjectOperations()
        coordinator._undo_service = Undo()
        coordinator._placement = FakePlacement()
        coordinator._toolbar = FakeToolbar()
        coordinator._nav = FakeNav()
        coordinator._viewer = FakeUnloadViewer()
        coordinator.visualization_service = FakeVisualization()
        coordinator.ui_access_manager = FakeAccess()
        coordinator._update_export_menu_state = lambda: None
        coordinator._save_current_page_view_state = lambda: None
        coordinator._flush_deferred_for_file = lambda _file_path: True
        coordinator._clear_mesh_views_for_scene_update = lambda **_call_options: None
        coordinator.handle_bid_selection(new_ref)
        self.assertIs(coordinator.ui_state_manager.get_selected_bid_ref(), old_ref)
        self.assertEqual(coordinator.ui_state_manager.page_selection, ["page-1"])
        self.assertEqual(coordinator.project_data.current_file, "old.mdb")
        self.assertEqual(coordinator.project_data.deselects, 0)
        self.assertEqual(coordinator._viewer.clears, 0)
        self.assertEqual(coordinator._undo_service.active, [])
        self.assertIs(coordinator.main_window.project_view.restored_bid, old_ref)

        class FailingSqlProjectOperations(ImmediateNavigationOperations):
            @staticmethod
            def load_bid(_bid_ref):
                raise DatabaseCatalogError("SQL bid read failed")

        coordinator.project_operations = FailingSqlProjectOperations()

        def assert_restored_before_warning(*_args):
            self.assertIs(coordinator.ui_state_manager.get_selected_bid_ref(), old_ref)
            self.assertEqual(coordinator.project_data.current_file, "old.mdb")

        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator.show_warning",
            side_effect=assert_restored_before_warning,
        ) as warning:
            coordinator.handle_bid_selection(new_ref)
        warning.assert_called_once_with(
            coordinator.main_window,
            "Open SQL Bid",
            "SQL bid read failed",
        )
        self.assertIs(coordinator.ui_state_manager.get_selected_bid_ref(), old_ref)
        self.assertEqual(coordinator.project_data.current_file, "old.mdb")
        self.assertEqual(coordinator._viewer.clears, 0)

    def test_clearing_bid_selection_clears_undo_owner(self):
        old_ref = BidRef("old.mdb", "old-bid")

        class UiState:
            def __init__(self):
                self.bid_ref = old_ref

            def get_selected_bid_ref(self):
                return self.bid_ref

            def set_bid_selection(self, bid_ref):
                self.bid_ref = bid_ref

            def set_database_selected(self, *_args):
                pass

            def set_file_path(self, *_args):
                pass

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeMainWindow()
        coordinator.project_operations = ImmediateNavigationOperations()
        coordinator._sql_collaboration = FakeSqlCollaboration()
        coordinator._plan_view_handler = None
        coordinator._status_panel = None
        coordinator.ui_state_manager = UiState()
        clear_bid_calls = []
        coordinator.project_data = type(
            "ProjectData",
            (),
            {
                "clear_bid": lambda _self: clear_bid_calls.append(True),
                "deselect_pages": lambda _self: None,
                "get_current_file_path": lambda _self: "old.mdb",
            },
        )()
        coordinator._undo_service = FakeUndo()
        coordinator._placement = FakePlacement()
        coordinator._toolbar = FakeToolbar()
        coordinator._viewer = FakeUnloadViewer()
        coordinator.visualization_service = FakeVisualization()
        coordinator.ui_access_manager = FakeAccess()
        coordinator._nav = FakeNav()
        coordinator._update_export_menu_state = lambda: None
        coordinator._save_current_page_view_state = lambda: None
        coordinator._flush_deferred_for_file = lambda _file_path: True
        coordinator._clear_mesh_views_for_scene_update = lambda **_call_options: None
        coordinator._reset_takeoff_workspace_state = lambda: None
        coordinator._set_takeoff_tab_visible = lambda _visible: None
        coordinator.handle_bid_selection(None)
        self.assertIsNone(coordinator.ui_state_manager.get_selected_bid_ref())
        self.assertEqual(coordinator._undo_service.active, [None])
        self.assertEqual(clear_bid_calls, [True])


class UIEventCoordinatorDeleteCurrentPageTests(
    _UIEventCoordinatorTakeoffsChangedFixture
):
    """UIEventCoordinator.delete_current_page."""

    def test_failed_page_delete_clears_pending_page_restore(self):
        from ost_visualizer.presentation.coordinators import ui_event_coordinator

        old_show_critical = ui_event_coordinator.show_critical
        ui_event_coordinator.show_critical = lambda *_args, **_call_options: None
        try:
            bid_ref = BidRef("bid.mdb", "bid-1")

            class UiState:
                active_page_uid = "p1"

                def get_selected_bid_ref(self):
                    return bid_ref

            class ProjectData:
                def get_page(self, uid):
                    return Page(uid=uid, name=uid) if uid in {"p1", "p2"} else None

                def get_page_takeoffs(self, _uid):
                    return []

                def get_page_annotations(self, _uid):
                    return []

            class ReadService:
                def get_pages_with_delete_content(self, _file_path, _bid_uid):
                    return set()

            class WriteService:
                def uses_sql_collaboration_mutations(self, _file_path):
                    return False

                def delete_pages(self, _file_path, _page_uids):
                    return False

            class TakeoffSidebar:
                def get_page_order(self):
                    return ["p1", "p2"]

            class Access:
                def is_allowed(self, _feature):
                    return True

            class MainWindow:
                def is_takeoff_tab_active(self):
                    return True

            coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
            coordinator.ui_state_manager = UiState()
            coordinator.project_data = ProjectData()
            coordinator._project_read_service = ReadService()
            coordinator._project_write_service = WriteService()
            coordinator.takeoff_sidebar = TakeoffSidebar()
            coordinator.ui_access_manager = Access()
            coordinator.main_window = MainWindow()
            coordinator._pending_takeoff_page_uids = None
            coordinator._pending_takeoff_active_page_uid = None
            coordinator._pending_takeoff_selected_area_uid = ""
            coordinator._pending_takeoff_place_condition_uid = None
            coordinator._pending_takeoff_place_condition_uids = []
            coordinator._deferred_persistence = FakeDeferredPersistence()
            coordinator.delete_current_page()
            self.assertIsNone(coordinator._pending_takeoff_page_uids)
            self.assertIsNone(coordinator._pending_takeoff_active_page_uid)
        finally:
            ui_event_coordinator.show_critical = old_show_critical

    def test_page_delete_revalidates_access_after_content_confirmation(self):
        bid_ref = BidRef("bid.mdb", "bid-1")
        page = Page(uid="p1", name="Page 1")
        delete_calls = []

        class Access:
            allowed = True

            def is_allowed(self, _feature):
                return self.allowed

        access = Access()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="p1",
            get_selected_bid_ref=lambda: bid_ref,
        )
        coordinator.project_data = SimpleNamespace(
            get_page=lambda uid: page if uid == "p1" else Page(uid=uid, name=uid),
            get_page_takeoffs=lambda _uid: [],
            get_page_annotations=lambda _uid: [],
        )
        coordinator._project_read_service = SimpleNamespace(
            get_pages_with_delete_content=lambda _file_path, _bid_uid: {"p1"}
        )
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: False,
            delete_pages=lambda *args: delete_calls.append(args) or True,
        )
        coordinator.takeoff_sidebar = SimpleNamespace(
            get_page_order=lambda: ["p1", "p2"]
        )
        coordinator.ui_access_manager = access
        coordinator.main_window = SimpleNamespace(is_takeoff_tab_active=lambda: True)
        coordinator._pending_takeoff_page_uids = None
        coordinator._pending_takeoff_active_page_uid = None
        coordinator._pending_takeoff_selected_area_uid = ""
        coordinator._pending_takeoff_place_condition_uid = None
        coordinator._pending_takeoff_place_condition_uids = []
        coordinator._deferred_persistence = FakeDeferredPersistence()

        def confirm_and_revoke(*_args):
            access.allowed = False
            return True

        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator."
            "confirm_delete_page_with_contents",
            side_effect=confirm_and_revoke,
        ):
            coordinator.delete_current_page()
        self.assertEqual(delete_calls, [])
        self.assertIsNone(coordinator._pending_takeoff_page_uids)

    def test_sql_page_delete_queues_without_calling_synchronous_writer(self):
        bid_ref = BidRef("sql-database", "7")

        class UiState:
            active_page_uid = "p1"

            def get_selected_bid_ref(self):
                return bid_ref

        class ProjectData:
            def get_page(self, uid):
                return Page(uid=uid, name=uid) if uid in {"p1", "p2"} else None

            def get_page_takeoffs(self, _uid):
                return []

            def get_page_annotations(self, _uid):
                return []

            def get_page_delete_content_snapshot(self, *_args):
                return set()

        class WriteService:
            queued = []

            def uses_sql_collaboration_mutations(self, _file_path):
                return True

            def queue_pages_delete(self, file_path, bid_uid, page_uids, callback):
                self.queued.append((file_path, bid_uid, list(page_uids), callback))
                return 9

            def delete_pages(self, *_args):
                raise AssertionError("SQL page deletion must not run synchronously")

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = UiState()
        coordinator.project_data = ProjectData()
        coordinator._project_read_service = SimpleNamespace(
            get_pages_with_delete_content=lambda *_args: set()
        )
        coordinator._project_write_service = WriteService()
        coordinator.takeoff_sidebar = SimpleNamespace(
            get_page_order=lambda: ["p1", "p2"]
        )
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        coordinator.main_window = SimpleNamespace(is_takeoff_tab_active=lambda: True)
        coordinator._pending_takeoff_page_uids = None
        coordinator._pending_takeoff_active_page_uid = None
        coordinator._pending_takeoff_selected_area_uid = ""
        coordinator._pending_takeoff_place_condition_uid = None
        coordinator._pending_takeoff_place_condition_uids = []
        coordinator._deferred_persistence = FakeDeferredPersistence()
        coordinator.delete_current_page()
        self.assertEqual(
            coordinator._project_write_service.queued[0][:3],
            ("sql-database", "7", ["p1"]),
        )
        self.assertEqual(coordinator._pending_takeoff_page_uids, ["p2"])


class UIEventCoordinatorFinishRefreshTests(_UIEventCoordinatorTakeoffsChangedFixture):
    """UIEventCoordinator._finish_refresh."""

    def test_database_refresh_restores_database_root_selection_and_hides_takeoff(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.main_window = FakeUnloadMainWindow()
        coordinator.project_data = FakeUnloadProjectData("active.mdb")
        coordinator._sql_collaboration = FakeSqlCollaboration()
        coordinator._status_panel = None
        coordinator.ui_access_manager = FakeAccess()
        coordinator._toolbar = FakeToolbar()
        coordinator._tab_widget = FakeTabWidget(index=1)
        coordinator._reset_takeoff_workspace_state = lambda: None
        coordinator._update_export_menu_state = lambda: None
        snapshot = FakeRefreshSnapshot(database_selected=True)
        coordinator._nav = FakeRefreshNav(snapshot)
        coordinator._finish_refresh()
        self.assertEqual(
            coordinator.main_window.project_view.restored_file,
            "active.mdb",
        )
        self.assertEqual(coordinator._tab_widget.visibility, [(1, False), (2, False)])
        self.assertEqual(coordinator._tab_widget.currentIndex(), 0)

    def test_database_refresh_restores_project_selection_with_file_path(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeUnloadMainWindow()
        coordinator.project_data = FakeUnloadProjectData("active.mdb", ["project-1"])
        coordinator._sql_collaboration = FakeSqlCollaboration()
        coordinator._status_panel = None
        coordinator.ui_access_manager = FakeAccess()
        coordinator._toolbar = FakeToolbar()
        coordinator._tab_widget = FakeTabWidget(index=0)
        coordinator._reset_takeoff_workspace_state = lambda: None
        coordinator._update_export_menu_state = lambda: None
        snapshot = FakeRefreshSnapshot(project_uid="project-1")
        coordinator._nav = FakeRefreshNav(snapshot)
        coordinator._finish_refresh()
        self.assertEqual(
            coordinator.main_window.project_view.restored_project,
            ("project-1", "active.mdb"),
        )

    def test_database_refresh_for_active_bid_preserves_sidebar_tree_state(self):
        bid_ref = BidRef("active.mdb", "bid-1")

        class Snapshot:
            page_uids = ["page-1"]
            active_page_uid = "page-1"
            highlighted_condition_uids = {"c1"}
            project_uid = None
            database_selected = False
            selected_file_path = "active.mdb"
            place_condition_uid = None
            place_condition_uids = []
            selected_area_uid = ""

            def __init__(self):
                self.bid_ref = bid_ref

        class UiState:
            selected_page_uids = ["page-1"]
            active_page_uid = "page-1"
            selected_area_uid = ""
            place_condition_uid = None
            place_condition_uids = []
            highlighted_condition_uids = {"c1"}

            def get_selected_bid_ref(self):
                return bid_ref

            def set_highlighted_conditions(self, uids):
                self.highlighted_condition_uids = set(uids)

            def set_page_selection(self, page_uids):
                self.selected_page_uids = list(page_uids)

        class ProjectData:
            def get_current_file_path(self):
                return "active.mdb"

            def get_bid(self, _bid_ref):
                return object()

            def get_current_bid_ref(self):
                return bid_ref

            def get_bid_conditions(self):
                return {"c1": object()}

            def get_page(self, page_uid):
                return object() if page_uid == "page-1" else None

            @staticmethod
            def select_pages(page_uids):
                return list(page_uids)

        class Nav:
            def __init__(self):
                self.refresh_snapshot = Snapshot()
                self.finished = []

            def finish_refresh(self, state):
                self.finished.append(state)

            def compute_state_for(self, has_file, bid_ref, active_page_uid):
                return "BID_ACTIVE"

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeUnloadMainWindow()
        coordinator.ui_state_manager = UiState()
        coordinator._sql_collaboration = FakeSqlCollaboration()
        coordinator._plan_view_handler = None
        coordinator._status_panel = None
        coordinator.project_data = ProjectData()
        coordinator.plan_view = None
        coordinator.ui_access_manager = FakeAccess()
        coordinator._toolbar = FakeToolbar()
        coordinator._tab_widget = FakeTabWidget(index=TAB_INDEX_TAKEOFF)
        coordinator._sidebar = FakeSidebar()
        coordinator._page_settings_bar = None
        coordinator._takeoff_workspace_bid_ref = bid_ref
        coordinator._pending_takeoff_page_uids = None
        coordinator._pending_takeoff_active_page_uid = None
        coordinator._pending_takeoff_selected_area_uid = ""
        coordinator._pending_takeoff_place_condition_uid = None
        coordinator._pending_takeoff_place_condition_uids = []
        coordinator._selected_takeoff_uids = ("t1",)
        coordinator._selection_projected_condition_uids = {"c1"}
        coordinator._resolve_bid_lock_state = lambda _bid_ref: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._activate_takeoff_workspace = lambda: None
        coordinator._nav = Nav()
        coordinator._finish_refresh()
        self.assertEqual(coordinator._sidebar.clears, 0)
        self.assertIsNone(coordinator._takeoff_workspace_bid_ref)
        self.assertEqual(coordinator._selected_takeoff_uids, ("t1",))
        self.assertEqual(coordinator._selection_projected_condition_uids, {"c1"})

    def test_database_refresh_resolves_deleted_page_while_summary_is_active(self):
        bid_ref = BidRef("active.mdb", "bid-1")
        remaining_page = Page(uid="page-2", name="Remaining", sequence=2)
        selected_pages = []
        page_settings = []

        class UiState:
            selected_page_uids = ["deleted-page"]
            active_page_uid = "deleted-page"
            highlighted_condition_uids = set()
            selected_area_uid = ""
            place_condition_uid = None
            place_condition_uids = []

            @staticmethod
            def get_selected_bid_ref():
                return bid_ref

            def set_page_selection(self, page_uids):
                self.selected_page_uids = list(page_uids)

            @staticmethod
            def set_highlighted_conditions(_uids):
                pass

        class ProjectData:
            @staticmethod
            def get_current_file_path():
                return bid_ref.file_path

            @staticmethod
            def get_current_bid_ref():
                return bid_ref

            @staticmethod
            def get_bid(ref):
                return object() if ref == bid_ref else None

            @staticmethod
            def get_bid_conditions():
                return {}

            @staticmethod
            def get_page(page_uid):
                return remaining_page if page_uid == remaining_page.uid else None

            @staticmethod
            def get_all_pages():
                return [remaining_page]

            @staticmethod
            def select_pages(page_uids):
                selected_pages.append(list(page_uids))
                return list(page_uids)

        snapshot = SimpleNamespace(
            bid_ref=bid_ref,
            page_uids=["deleted-page"],
            active_page_uid="deleted-page",
            highlighted_condition_uids=set(),
            project_uid=None,
            database_selected=False,
            selected_file_path=bid_ref.file_path,
            place_condition_uid=None,
            place_condition_uids=[],
            selected_area_uid="",
        )
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeUnloadMainWindow()
        coordinator.ui_state_manager = UiState()
        coordinator.project_data = ProjectData()
        coordinator.project_operations = ImmediateNavigationOperations()
        coordinator.ui_access_manager = FakeAccess()
        coordinator._toolbar = FakeToolbar()
        coordinator._viewer = FakeUnloadViewer()
        coordinator._tab_widget = FakeTabWidget(index=TAB_INDEX_SUMMARY)
        coordinator._view_stack = FakeViewStack(index=1)
        coordinator._status_panel = _CollaborationStatusPanel()
        coordinator._sidebar = FakeSidebar()
        coordinator._page_settings_bar = object()
        coordinator._placement = FakePlacement()
        coordinator._takeoff_workspace_bid_ref = bid_ref
        coordinator._pending_takeoff_page_uids = None
        coordinator._pending_takeoff_active_page_uid = None
        coordinator._pending_takeoff_selected_area_uid = ""
        coordinator._pending_takeoff_place_condition_uid = None
        coordinator._pending_takeoff_place_condition_uids = []
        coordinator._resolve_bid_lock_state = lambda _bid_ref: None
        coordinator._reset_takeoff_workspace_state = lambda **_options: None
        coordinator._update_page_settings_bar = lambda page_uid: page_settings.append(
            page_uid
        )
        coordinator._load_condition_summary = lambda: None
        coordinator._nav = FakeRefreshNav(snapshot)
        coordinator._nav.compute_state_for = NavigationStateMachine().compute_state_for
        coordinator._finish_refresh()
        self.assertEqual(coordinator.ui_state_manager.selected_page_uids, ["page-2"])
        self.assertEqual(coordinator.ui_state_manager.active_page_uid, "page-2")
        self.assertEqual(selected_pages, [["page-2"]])
        self.assertEqual(page_settings, ["page-2"])
        self.assertEqual(coordinator._viewer.clears, 1)
        self.assertEqual(
            coordinator._nav.state,
            NavState.BID_ACTIVE_PAGES_SELECTED,
        )
        self.assertEqual(coordinator._toolbar.refreshes, 1)
        self.assertEqual(coordinator._status_panel.page_info, "Remaining")

    def test_database_refresh_drops_deleted_project_selection_and_hides_takeoff(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeUnloadMainWindow()
        coordinator.project_data = FakeUnloadProjectData("active.mdb", [])
        coordinator._sql_collaboration = FakeSqlCollaboration()
        coordinator._status_panel = None
        coordinator.ui_state_manager = FakeRefreshUiState()
        coordinator.ui_access_manager = FakeAccess()
        coordinator._toolbar = FakeToolbar()
        coordinator._tab_widget = FakeTabWidget(index=1)
        coordinator._sidebar = FakeSidebar()
        coordinator._reset_takeoff_workspace_state = (
            lambda: coordinator._sidebar.clear_sidebars()
        )
        coordinator._update_export_menu_state = lambda: None
        snapshot = FakeRefreshSnapshot(project_uid="deleted-project")
        coordinator._nav = FakeRefreshNav(snapshot)
        coordinator._finish_refresh()
        self.assertEqual(coordinator.ui_state_manager.reset_count, 1)
        self.assertEqual(
            coordinator.ui_state_manager.database_selected,
            (True, "active.mdb"),
        )
        self.assertEqual(coordinator._sidebar.clears, 1)
        self.assertEqual(coordinator._tab_widget.visibility, [(1, False), (2, False)])
        self.assertEqual(coordinator._tab_widget.currentIndex(), 0)
        self.assertIsNone(coordinator.main_window.project_view.restored_project)
        self.assertEqual(
            coordinator.main_window.project_view.restored_file, "active.mdb"
        )

    def test_database_refresh_drops_deleted_bid_and_clears_stale_main_plan(self):
        class ProjectData(FakeUnloadProjectData):
            def __init__(self):
                super().__init__("active.mdb", [])
                self.deselect_count = 0

            def get_bid(self, _bid_ref):
                return None

            def deselect_pages(self):
                self.deselect_count += 1

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeUnloadMainWindow()
        coordinator.project_data = ProjectData()
        coordinator._sql_collaboration = FakeSqlCollaboration()
        coordinator._status_panel = None
        coordinator.ui_state_manager = FakeRefreshUiState()
        deleted_bid_ref = BidRef("active.mdb", "deleted-bid")
        coordinator.ui_state_manager.bid_ref = deleted_bid_ref
        coordinator.ui_access_manager = FakeAccess()
        coordinator._toolbar = FakeToolbar()
        coordinator._viewer = FakeUnloadViewer()
        coordinator._tab_widget = FakeTabWidget(index=1)
        coordinator._sidebar = FakeSidebar()
        coordinator._reset_takeoff_workspace_state = (
            lambda: coordinator._sidebar.clear_sidebars()
        )
        undo_calls = []
        coordinator._sync_undo_bid = lambda: undo_calls.append(
            coordinator.ui_state_manager.get_selected_bid_ref()
        )
        scene_clears = []
        discarded_cameras = []
        coordinator._clear_mesh_views_for_scene_update = lambda: scene_clears.append(
            True
        )
        coordinator._discard_mesh_camera_states = (
            lambda **identity: discarded_cameras.append(identity)
        )
        snapshot = FakeRefreshSnapshot(bid_ref=deleted_bid_ref)
        coordinator._nav = FakeRefreshNav(snapshot)
        coordinator._finish_refresh()
        self.assertEqual(coordinator._sidebar.clears, 1)
        self.assertIsNone(coordinator.ui_state_manager.get_selected_bid_ref())
        self.assertEqual(undo_calls, [None])
        self.assertEqual(coordinator.project_data.deselect_count, 1)
        self.assertEqual(coordinator._tab_widget.visibility, [(1, False), (2, False)])
        self.assertEqual(coordinator._tab_widget.currentIndex(), 0)
        self.assertEqual(
            coordinator.main_window.project_view.restored_file, "active.mdb"
        )
        self.assertEqual(coordinator._nav.state.name, "FILE_LOADED_NO_BID")
        self.assertEqual(scene_clears, [True])
        self.assertEqual(discarded_cameras, [{"bid_ref": deleted_bid_ref}])
        self.assertEqual(coordinator._viewer.clears, 1)
        self.assertEqual(coordinator._toolbar.refreshes, 1)

    def test_database_refresh_loads_replacement_bid_selected_after_delete(self):
        replacement_ref = BidRef("active.mdb", "bid-2")

        class UiState:
            selected_page_uids = []
            active_page_uid = None
            highlighted_condition_uids = set()
            selected_project_uid = None
            place_condition_uid = None
            place_condition_uids = []
            selected_area_uid = ""

            def __init__(self):
                self.bid_ref = replacement_ref
                self.page_selection = None

            @property
            def selected_file_path(self):
                return self.bid_ref.file_path if self.bid_ref else None

            def get_selected_bid_ref(self):
                return self.bid_ref

            def set_bid_selection(self, bid_ref):
                self.bid_ref = bid_ref

            def set_page_selection(self, page_uids):
                self.page_selection = list(page_uids)

            def is_database_selected(self):
                return False

        class ProjectData:
            def __init__(self):
                self.current_bid_ref = None
                self.current_file = "active.mdb"
                self.deselect_count = 0

            def get_current_file_path(self):
                return self.current_file

            def get_current_bid_ref(self):
                return self.current_bid_ref

            def get_bid(self, bid_ref):
                return object() if bid_ref == replacement_ref else None

            def set_current_file(self, file_path):
                self.current_file = file_path

            def deselect_pages(self):
                self.deselect_count += 1

        class ProjectOperations(ImmediateNavigationOperations):
            def __init__(self, project_data):
                self.project_data = project_data
                self.loaded = []

            def load_bid(self, bid_ref):
                self.loaded.append(bid_ref)
                self.project_data.current_bid_ref = bid_ref
                return True

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.main_window = FakeUnloadMainWindow()
        coordinator.ui_state_manager = UiState()
        coordinator._sql_collaboration = FakeSqlCollaboration()
        coordinator._plan_view_handler = None
        coordinator._status_panel = None
        coordinator.project_data = ProjectData()
        coordinator.project_operations = ProjectOperations(coordinator.project_data)
        coordinator.ui_access_manager = FakeAccess()
        coordinator._toolbar = FakeToolbar()
        coordinator._tab_widget = FakeTabWidget(index=0)
        coordinator._placement = FakePlacement()
        coordinator._viewer = FakeUnloadViewer()
        coordinator.visualization_service = FakeVisualization()
        coordinator._nav = FakeRefreshNav(FakeRefreshSnapshot(bid_ref=replacement_ref))
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator._last_mesh_scene = None
        coordinator._mesh_scene_dirty = False
        coordinator._dirty_mesh_page_uids = set()
        coordinator._pending_dirty_mesh_refresh = False
        coordinator._save_current_page_view_state = lambda: None
        coordinator._sync_undo_bid = lambda: None
        coordinator.ensure_select_mode = lambda: None
        coordinator._resolve_bid_lock_state = lambda _bid_ref: None
        coordinator._reset_takeoff_workspace_state = lambda: None
        coordinator._clear_mesh_views_for_scene_update = lambda **_call_options: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._finish_refresh()
        self.assertEqual(
            coordinator.main_window.project_view.restored_bid, replacement_ref
        )
        self.assertEqual(coordinator.project_operations.loaded, [replacement_ref])
        self.assertEqual(
            coordinator.project_data.get_current_bid_ref(), replacement_ref
        )
        self.assertEqual(coordinator._tab_widget.visibility, [(1, True), (2, True)])

    def test_database_refresh_does_not_restore_invalidated_placement(self):
        bid_ref = BidRef("active.mdb", "bid-1")
        staged = []
        select_resets = []

        class Placement(FakePlacement):
            def __init__(self):
                super().__init__()
                self.is_active = True

            def reconcile_authoritative_conditions(
                self, *, accept_reconstructed_conditions=False
            ):
                _ = accept_reconstructed_conditions
                self.reconciliation_calls += 1
                self.force_exit()
                return False

        snapshot = SimpleNamespace(
            bid_ref=bid_ref,
            project_uid=None,
            database_selected=False,
            selected_file_path=bid_ref.file_path,
            page_uids=["page-1"],
            active_page_uid="page-1",
            highlighted_condition_uids=set(),
            selected_area_uid="",
            place_condition_uid="condition-1",
            place_condition_uids=["condition-1", "deleted-secondary"],
        )
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeUnloadMainWindow()
        coordinator.project_data = SimpleNamespace(
            get_current_file_path=lambda: bid_ref.file_path,
            get_current_bid_ref=lambda: bid_ref,
            get_bid=lambda ref: object() if ref == bid_ref else None,
            get_bid_conditions=lambda: {
                "condition-1": Condition(
                    uid="condition-1",
                    layer_visible=True,
                    condition_type=Condition.TYPE_AREA,
                )
            },
            get_page=lambda uid: object() if uid == "page-1" else None,
            select_pages=lambda page_uids: list(page_uids),
        )
        coordinator.ui_state_manager = SimpleNamespace(
            selected_page_uids=["page-1"],
            active_page_uid="page-1",
            set_highlighted_conditions=lambda _uids: None,
            set_page_selection=lambda _uids: None,
        )
        coordinator._placement = Placement()
        coordinator._nav = SimpleNamespace(
            refresh_snapshot=snapshot,
            compute_state_for=lambda **_context: NavState.BID_ACTIVE_PAGES_SELECTED,
            finish_refresh=lambda _state: None,
        )
        coordinator._tab_widget = None
        coordinator._status_panel = None
        coordinator.ui_access_manager = FakeAccess()
        coordinator._toolbar = FakeToolbar()
        coordinator._resolve_bid_lock_state = lambda _bid_ref: None
        coordinator._reset_takeoff_workspace_state = lambda **_options: None
        coordinator._validate_condition_uids = lambda uids: set(uids)
        coordinator._is_condition_placeable = lambda _uid: True
        coordinator._set_plan_select_mode = lambda: select_resets.append(True)
        coordinator._stage_takeoff_restore = lambda **values: staged.append(values)
        coordinator._update_menu_state = lambda: None
        coordinator._finish_refresh()
        self.assertEqual(coordinator._placement.reconciliation_calls, 1)
        self.assertEqual(select_resets, [True])
        self.assertIsNone(staged[0]["place_condition_uid"])
        self.assertEqual(staged[0]["place_condition_uids"], [])

        class CancelledPlacement(FakePlacement):
            def reconcile_authoritative_conditions(
                self, *, accept_reconstructed_conditions=False
            ):
                _ = accept_reconstructed_conditions
                self.reconciliation_calls += 1
                return True

        staged.clear()
        select_resets.clear()
        coordinator._placement = CancelledPlacement()
        coordinator._finish_refresh()
        self.assertEqual(coordinator._placement.reconciliation_calls, 0)
        self.assertEqual(select_resets, [])
        self.assertIsNone(staged[0]["place_condition_uid"])
        self.assertEqual(staged[0]["place_condition_uids"], [])


class SummaryTabCoordinatorTests(unittest.TestCase):
    def test_condition_layer_visibility_path_updates_summary_without_reload(self):
        conditions = {
            "c1": Condition(uid="c1", name="A", layer_uid="layer-a"),
            "c2": Condition(uid="c2", name="B", layer_uid="layer-b"),
        }
        layers = [SimpleNamespace(uid="layer-a", show=True)]
        bid_owner = object()

        class FakeProjectData:
            def get_bid(self, _bid_ref):
                return bid_owner

            def get_bid_conditions(self):
                return conditions

            def get_bid_layer_snapshot(self):
                return list(layers)

            def is_image_layer_uid(self, _layer_uid):
                return False

            def update_layer_visibility(self, layer_uid, show):
                for layer in layers:
                    if str(layer.uid) == str(layer_uid):
                        layer.show = bool(show)
                for condition in conditions.values():
                    if str(condition.layer_uid or "") == str(layer_uid):
                        condition.layer_visible = bool(show)
                return []

            def get_selected_page_uids(self):
                return []

        class FakeConditionsSidebar:
            def __init__(self):
                self.calls = []

            def apply_layer_visibility_state(
                self, applied_conditions, grayscale, layer_uid=None
            ):
                self.calls.append((applied_conditions, grayscale, layer_uid))

        class FakeSummaryTab:
            def __init__(self):
                self.calls = []

            def apply_layer_visibility_state(
                self, applied_conditions, grayscale, layer_uid=None
            ):
                self.calls.append((applied_conditions, grayscale, layer_uid))

        class FakeLayersSidebar:
            def __init__(self):
                self.calls = []

            def set_layer_visible(self, layer_uid, show):
                self.calls.append((layer_uid, show))

            def get_layer_visibility(self, layer_uid):
                return next(
                    (
                        bool(layer.show)
                        for layer in layers
                        if str(layer.uid) == str(layer_uid)
                    ),
                    None,
                )

        loads = []
        layers_sidebar = FakeLayersSidebar()
        conditions_sidebar = FakeConditionsSidebar()
        summary_tab = FakeSummaryTab()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        coordinator.project_data = FakeProjectData()
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="",
            get_selected_bid_ref=lambda: BidRef("db.mdb", "bid-1"),
            state=SimpleNamespace(grayscale_enabled=False),
        )
        coordinator._sidebar = SimpleNamespace(bid_layers_sidebar=layers_sidebar)
        coordinator.conditions_sidebar = conditions_sidebar
        coordinator.condition_summary_tab = summary_tab
        coordinator.event_bus = SimpleNamespace(
            publish=lambda *_args, **_call_options: None
        )
        coordinator._deferred_persistence = SimpleNamespace(
            schedule_layer_show=lambda _db_path, _layer_uid, _show, **_callbacks: True
        )
        coordinator.plan_view = None
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator._mesh_scene_dirty = False
        coordinator._dirty_mesh_page_uids = set()
        coordinator._pending_dirty_mesh_refresh = False
        coordinator._last_mesh_scene = None
        coordinator.visualization_service = SimpleNamespace(
            cancel_mesh_view_refresh=lambda: None,
            refresh_mesh_view=lambda _page_uids: None,
        )
        coordinator._toolbar = SimpleNamespace(refresh=lambda: None)
        coordinator._suspend_active_layer_tool = lambda _layer_uid=None: None
        coordinator._restore_suspended_layer_tool = lambda _layer_uid=None: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._load_condition_summary = lambda: loads.append("load")
        self.assertTrue(
            UIEventCoordinator.update_layer_visibility_deferred(
                coordinator, "layer-a", False
            )
        )
        self.assertFalse(conditions["c1"].layer_visible)
        self.assertTrue(conditions["c2"].layer_visible)
        self.assertEqual(layers_sidebar.calls, [("layer-a", False)])
        self.assertEqual(conditions_sidebar.calls, [(conditions, False, "layer-a")])
        self.assertEqual(summary_tab.calls, [(conditions, False, "layer-a")])
        self.assertEqual(loads, [])

    def test_summary_tab_visibility_tracks_takeoff_tab(self):
        class FakeTabWidget:
            def __init__(self):
                self.visible = {}
                self.current = TAB_INDEX_SUMMARY

            def setTabVisible(self, index, visible):
                self.visible[index] = visible

            def currentIndex(self):
                return self.current

            def count(self):
                return 3

            def setCurrentIndex(self, index):
                self.current = index

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._tab_widget = FakeTabWidget()
        UIEventCoordinator._set_takeoff_tab_visible(coordinator, True)
        self.assertTrue(coordinator._tab_widget.visible[TAB_INDEX_TAKEOFF])
        self.assertTrue(coordinator._tab_widget.visible[TAB_INDEX_SUMMARY])
        UIEventCoordinator._set_takeoff_tab_visible(coordinator, False)
        self.assertFalse(coordinator._tab_widget.visible[TAB_INDEX_TAKEOFF])
        self.assertFalse(coordinator._tab_widget.visible[TAB_INDEX_SUMMARY])
        self.assertEqual(coordinator._tab_widget.current, TAB_INDEX_PROJECTS)

    def test_ost_status_path_does_not_clear_populated_summary_tree(self):
        _app()
        tab = ConditionSummaryTab(
            None, uom_label_fn=lambda _code: "EA", delete_allowed_fn=lambda: True
        )
        header_controller = _attach_summary_header(tab)
        service = ConditionSummaryService()
        grouping = ConditionSummaryGrouping(by_page=True, by_type=True)
        root = service.build_summary(
            conditions={
                "c1": Condition(
                    uid="c1",
                    name="Fdn1",
                    condition_type=Condition.TYPE_COUNT,
                    uom1=UOM_EACH,
                    calc_type1=CALC_COUNT,
                    ref_no=1,
                ),
                "unused": Condition(
                    uid="unused",
                    name="Unused",
                    condition_type=Condition.TYPE_COUNT,
                    uom1=UOM_EACH,
                    calc_type1=CALC_COUNT,
                    ref_no=2,
                ),
            },
            folders={},
            takeoffs=[Takeoff(uid="tk1", condition_uid="c1", page_uid="p1")],
            pages=[Page(uid="p1", name="S-100.pdf", sequence=1)],
            areas=[],
            grouping=grouping,
        )
        tab.load_summary(root, grouping)
        tab.tree.header().resizeSection(tab.column_keys.index("name"), 211)
        tab.tree.header().resizeSection(tab.column_keys.index("quantity1"), 97)
        tab.resize(900, 400)
        tab.show()
        _app().processEvents()
        name_col = next(
            index
            for index in range(tab.tree.columnCount())
            if tab.tree.headerItem().text(index) == "Name"
        )
        quantity_col = next(
            index
            for index in range(tab.tree.columnCount())
            if tab.tree.headerItem().text(index) == "Quantity 1"
        )
        refreshes = []
        original_refresh = tab.refresh_view
        tab.refresh_view = lambda: (refreshes.append("refresh"), original_refresh())
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.condition_summary_tab = tab
        coordinator.ensure_select_mode = lambda: None
        coordinator._menu_state_signaler = type(
            "FakeSignaler", (), {"request": lambda self: None}
        )()
        UIEventCoordinator._on_ost_status_changed(coordinator, active=True)
        _app().processEvents()
        self.assertEqual(refreshes, ["refresh"])
        self.assertGreater(tab.tree.topLevelItemCount(), 0)
        self.assertGreater(
            tab.tree.visualItemRect(tab.tree.topLevelItem(0)).height(), 0
        )
        self.assertEqual(tab.grouping, grouping)
        self.assertEqual(tab.tree.header().sectionSize(name_col), 211)
        self.assertEqual(tab.tree.header().sectionSize(quantity_col), 97)
        self.assertEqual(_condition_row_uids(root), ["c1"])
        del header_controller
        tab.deleteLater()

    def test_database_refresh_after_ost_status_keeps_summary_tree_visible(self):
        _app()
        tab = ConditionSummaryTab(
            None, uom_label_fn=lambda _code: "EA", delete_allowed_fn=lambda: True
        )
        header_controller = _attach_summary_header(tab)
        service = ConditionSummaryService()
        grouping = ConditionSummaryGrouping(by_type=True, by_area=True)
        root = service.build_summary(
            conditions={
                "c1": Condition(
                    uid="c1",
                    name="Fdn1",
                    condition_type=Condition.TYPE_COUNT,
                    uom1=UOM_EACH,
                    calc_type1=CALC_COUNT,
                    ref_no=1,
                ),
                "unused": Condition(uid="unused", name="Unused", ref_no=2),
            },
            folders={},
            takeoffs=[Takeoff(uid="tk1", condition_uid="c1", page_uid="p1")],
            pages=[Page(uid="p1", name="S-100.pdf", sequence=1)],
            areas=[BidArea(uid="0", bid_uid="b1", parent_uid="", name="", sequence=1)],
            grouping=grouping,
        )
        tab.load_summary(root, grouping)
        tab.tree.header().resizeSection(tab.column_keys.index("name"), 211)
        tab.resize(900, 400)
        tab.show()
        _app().processEvents()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.condition_summary_tab = tab
        coordinator.ensure_select_mode = lambda: None
        coordinator._menu_state_signaler = type(
            "FakeSignaler", (), {"request": lambda self: None}
        )()
        UIEventCoordinator._on_ost_status_changed(coordinator, active=True)
        coordinator._deferred_persistence = SimpleNamespace(
            flush_for_file=lambda _file_path: True
        )
        coordinator._nav = SimpleNamespace(
            start_refresh=lambda ui_state, placement, selected_area_uid="": True
        )
        coordinator.ui_state_manager = SimpleNamespace(
            selected_area_uid="",
            selected_page_uids=[],
            get_selected_bid_ref=lambda: None,
        )
        coordinator._mesh_scene_dirty = False
        coordinator._placement = SimpleNamespace()
        coordinator._do_file_refresh = lambda: None
        coordinator._finish_refresh = lambda: None
        UIEventCoordinator._on_database_refreshed(coordinator, file_path="a.mdb")
        _app().processEvents()
        self.assertGreater(tab.tree.topLevelItemCount(), 0)
        self.assertGreater(
            tab.tree.visualItemRect(tab.tree.topLevelItem(0)).height(), 0
        )
        self.assertEqual(tab.grouping, grouping)
        self.assertEqual(_condition_row_uids(root), ["c1"])
        del header_controller
        tab.deleteLater()

    def test_database_refresh_while_summary_tab_active_reloads_cleared_summary(self):
        _app()
        bid_ref = BidRef("a.mdb", "bid-1")
        tab = ConditionSummaryTab(
            None, uom_label_fn=lambda _code: "EA", delete_allowed_fn=lambda: True
        )
        service = ConditionSummaryService()
        grouping = ConditionSummaryGrouping(by_type=True, by_area=True)
        conditions = {
            "c1": Condition(
                uid="c1",
                name="Fdn1",
                condition_type=Condition.TYPE_COUNT,
                uom1=UOM_EACH,
                calc_type1=CALC_COUNT,
                ref_no=1,
            ),
            "unused": Condition(uid="unused", name="Unused", ref_no=2),
        }
        takeoffs = [Takeoff(uid="tk1", condition_uid="c1", page_uid="p1")]
        pages = [Page(uid="p1", name="S-100.pdf", sequence=1)]

        def build_root():
            return service.build_summary(
                conditions=conditions,
                folders={},
                takeoffs=takeoffs,
                pages=pages,
                areas=[],
                grouping=grouping,
            )

        tab.load_summary(build_root(), grouping)
        self.assertGreater(tab.tree.topLevelItemCount(), 0)

        class FakeSidebar:
            def __init__(self):
                self.loads = 0

            def clear_sidebars(self):
                tab.clear()

            def load_condition_summary(self):
                self.loads += 1
                tab.load_summary(build_root(), grouping)

        class FakeTabWidget:
            def currentIndex(self):
                return TAB_INDEX_SUMMARY

        class FakeProjectView:
            def restore_bid_selection(self, _bid_ref):
                pass

        class FakeNav:
            def __init__(self):
                self.refresh_snapshot = SimpleNamespace(
                    bid_ref=bid_ref,
                    page_uids=["p1"],
                    active_page_uid="p1",
                    highlighted_condition_uids=set(),
                    project_uid=None,
                    database_selected=False,
                    selected_file_path="a.mdb",
                    place_condition_uid=None,
                    place_condition_uids=[],
                    selected_area_uid="",
                )

            def compute_state_for(self, has_file, bid_ref, active_page_uid):
                del has_file, bid_ref, active_page_uid
                return NavState.BID_ACTIVE_PAGES_SELECTED

            def finish_refresh(self, _state):
                self.refresh_snapshot = None

        fake_sidebar = FakeSidebar()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.plan_view = None
        coordinator._nav = FakeNav()
        coordinator._sidebar = fake_sidebar
        coordinator._tab_widget = FakeTabWidget()
        coordinator._page_settings_bar = None
        coordinator._takeoff_workspace_bid_ref = bid_ref
        coordinator._selected_takeoff_uids = ()
        coordinator._selection_projected_condition_uids = set()
        coordinator._clear_staged_takeoff_restore = lambda: None
        coordinator._resolve_bid_lock_state = lambda _bid_ref: None
        coordinator._is_condition_placeable = lambda _condition_uid: True
        coordinator._stage_takeoff_restore = (
            lambda page_uids=None, active_page_uid=None, selected_area_uid="", place_condition_uid=None, place_condition_uids=None: None
        )
        coordinator._activate_takeoff_workspace = lambda: None
        coordinator._set_takeoff_tab_visible = lambda _visible: None
        coordinator._sync_undo_bid = lambda: None
        coordinator._reset_to_select_mode = lambda: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._update_menu_state = lambda: None
        coordinator.condition_summary_tab = tab
        coordinator.ui_access_manager = SimpleNamespace(refresh=lambda: None)
        coordinator.ui_state_manager = SimpleNamespace(
            selected_page_uids=["p1"],
            active_page_uid="p1",
            get_selected_bid_ref=lambda: bid_ref,
            set_highlighted_conditions=lambda _uids: None,
            set_page_selection=lambda _uids: None,
            set_bid_selection=lambda _bid_ref: None,
        )
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: False
        )
        coordinator.project_data = SimpleNamespace(
            get_current_file_path=lambda: "a.mdb",
            get_bid=lambda _bid_ref: object(),
            get_current_bid_ref=lambda: bid_ref,
            get_bid_conditions=lambda: conditions,
            get_page=lambda uid: pages[0] if uid == "p1" else None,
            get_all_pages=lambda: list(pages),
            select_pages=lambda page_uids: list(page_uids),
            deselect_pages=lambda: None,
        )
        coordinator.main_window = SimpleNamespace(
            project_view=FakeProjectView(),
            refresh_window_title=lambda: None,
        )
        coordinator._toolbar = SimpleNamespace(refresh=lambda: None)
        coordinator._status_panel = None
        UIEventCoordinator._finish_refresh(coordinator)
        self.assertEqual(fake_sidebar.loads, 1)
        self.assertGreater(tab.tree.topLevelItemCount(), 0)
        self.assertEqual(_condition_row_uids(tab._root_node), ["c1"])
        tab.deleteLater()

    def test_delete_condition_flow_uses_shared_condition_event_projection(self):
        from ost_visualizer.presentation.handlers import condition_action_handler

        conditions = {
            "c1": Condition(uid="c1", name="Fdn1"),
            "c2": Condition(uid="c2", name="Fdn2"),
        }
        takeoffs = [Takeoff(uid="tk1", condition_uid="c1", page_uid="p1")]
        tab = ConditionSummaryTab(
            None, uom_label_fn=lambda _code: "EA", delete_allowed_fn=lambda: True
        )
        service = ConditionSummaryService()

        def reload_summary():
            root = service.build_summary(
                conditions=conditions,
                folders={},
                takeoffs=takeoffs,
                pages=[Page(uid="p1", name="S-100.pdf", sequence=1)],
                areas=[],
                grouping=tab.grouping,
            )
            tab.load_summary(root, tab.grouping)

        condition_event_projections = []

        class FakeWriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return False

            def delete_conditions(self, _file_path, _bid_uid, condition_uids):
                for uid in condition_uids:
                    conditions.pop(uid, None)
                condition_event_projections.append("conditions_changed")
                reload_summary()
                return True

        class FakeSidebar:
            def window(self):
                return None

            def get_condition_name(self, uid):
                return conditions[uid].name

            def condition_selection_after_delete(self, _condition_uids):
                return None

        coordinator = type(
            "FakeCoordinator",
            (),
            {
                "ui_access_manager": _FakeSummaryAccess({Feature.DELETE_CONDITION}),
                "conditions_sidebar": FakeSidebar(),
                "placement": type(
                    "FakePlacement", (), {"force_exit": lambda self: None}
                )(),
                "flush_deferred_for_file": lambda self, _file_path: True,
                "highlight_sidebar": lambda self, _uids, reveal=True: None,
                "ensure_select_mode": lambda self: None,
            },
        )()
        ui_state = type(
            "FakeUiState",
            (),
            {
                "highlighted_condition_uids": {"c1", "c2"},
                "get_selected_bid_ref": lambda self: BidRef("db.mdb", "bid-1"),
            },
        )()
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=FakeWriteService(),
            project_read_service=None,
            project_data=type(
                "FakeProjectData",
                (),
                {"get_bid_conditions": lambda self: conditions},
            )(),
            ui_state_manager=ui_state,
            workspace_state_model=make_workspace_state_model(),
        )
        original_confirm = condition_action_handler.confirm_delete_conditions
        condition_action_handler.confirm_delete_conditions = lambda _parent, names: [
            uid for uid, _name in names
        ]
        try:
            reload_summary()
            handler.on_delete_requested(["c1"])
        finally:
            condition_action_handler.confirm_delete_conditions = original_confirm
            tab.deleteLater()
        self.assertEqual(condition_event_projections, ["conditions_changed"])
        self.assertNotIn("c1", conditions)
        self.assertEqual(tab.tree.topLevelItemCount(), 0)


class DeferredPersistenceCoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _install_hidden_2d_mesh_state(self, coordinator):
        mesh_refresh_calls = []
        coordinator._tab_widget = FakeIndexWidget(TAB_INDEX_TAKEOFF)
        coordinator._view_stack = FakeIndexWidget(1)
        coordinator._mesh_window = None
        coordinator.opengl_viewer = None
        coordinator._mesh_scene_dirty = False
        coordinator._dirty_mesh_page_uids = set()
        coordinator._pending_dirty_mesh_refresh = False
        coordinator._last_mesh_scene = None
        coordinator.visualization_service = SimpleNamespace(
            refresh_mesh_view=lambda page_uids: mesh_refresh_calls.append(
                list(page_uids)
            )
        )
        coordinator.mesh_refresh_calls = mesh_refresh_calls
        return mesh_refresh_calls

    @staticmethod
    def _install_native_mesh_recorders(coordinator):
        coordinator.opengl_viewer = RecordingNativeMeshView()
        coordinator._mesh_window = RecordingNativeMeshView()

    def _make_view_state_coordinator(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator._plan_view_handler = None
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: False
        )
        coordinator._sql_collaboration = SimpleNamespace(
            update_presence=lambda _database_id, _bid_uid, _page_uid, mode=None: None
        )
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("a.mdb", "bid-1"),
            active_page_uid="p1",
        )
        pages = {
            "p1": Page(uid="p1", name="P1"),
            "p2": Page(uid="p2", name="P2"),
        }
        coordinator.project_data = SimpleNamespace(
            get_page=lambda page_uid: pages.get(page_uid),
        )
        coordinator.plan_view = SimpleNamespace(
            current_page_uid="p1",
            is_view_state_stable=True,
            get_view_state=lambda: (2.5, 10.0, 20.0),
        )
        coordinator._deferred_persistence = RecordingDeferredPersistence()
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        coordinator._nav = NavigationStateMachine()
        coordinator._nav.transition_to(NavState.FILE_LOADED_NO_BID)
        coordinator._nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)
        coordinator._nav.transition_to(NavState.BID_ACTIVE_PAGES_SELECTED)
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        return coordinator, pages

    def test_plan_view_state_change_updates_model_and_defers_write(self):
        coordinator, pages = self._make_view_state_coordinator()
        direct_writes = []
        coordinator._project_write_service = SimpleNamespace(
            save_page_view_state=lambda db_path, page_uid, zoom_fac, current_x, current_y: direct_writes.append(
                (db_path, page_uid, zoom_fac, current_x, current_y)
            )
        )
        coordinator._on_plan_view_state_changed("p1", 3.0, 30.0, 40.0)
        self.assertEqual(pages["p1"].zoom_fac, 3.0)
        self.assertEqual(pages["p1"].current_x, 30.0)
        self.assertEqual(pages["p1"].current_y, 40.0)
        self.assertEqual(
            coordinator._deferred_persistence.page_view_calls,
            [("a.mdb", "bid-1", "p1", 3.0, 30.0, 40.0)],
        )
        self.assertEqual(direct_writes, [])

    def test_reset_or_current_state_capture_defers_page_view_persistence(self):
        coordinator, pages = self._make_view_state_coordinator()
        coordinator._save_current_page_view_state()
        self.assertEqual(pages["p1"].zoom_fac, 2.5)
        self.assertEqual(
            coordinator._deferred_persistence.page_view_calls,
            [("a.mdb", "bid-1", "p1", 2.5, 10.0, 20.0)],
        )

    def test_active_page_switch_defers_selected_page_and_outgoing_view_state(self):
        coordinator, _pages = self._make_view_state_coordinator()
        interaction_cancellations = []
        coordinator._plan_view_handler = SimpleNamespace(
            prepare_for_authoritative_refresh=lambda: interaction_cancellations.append(
                "cancel"
            )
        )
        self._install_native_mesh_recorders(coordinator)
        coordinator._update_page_settings_bar = lambda _page_uid: None
        coordinator._sync_overlay_display_mode = lambda _page_uid: None
        coordinator._update_plan_view = lambda _page_uid: None
        coordinator._sidebar = SimpleNamespace(
            update_conditions_quantities=lambda: None
        )
        coordinator._placement = SimpleNamespace(is_active=False)
        coordinator._sync_page_info_status = lambda: None
        coordinator._update_export_menu_state = lambda: None
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        coordinator.handle_active_page_changed("p2")
        self.assertEqual(
            coordinator._deferred_persistence.page_view_calls,
            [("a.mdb", "bid-1", "p1", 2.5, 10.0, 20.0)],
        )
        self.assertEqual(
            coordinator._deferred_persistence.selected_page_calls,
            [("a.mdb", "bid-1", "p2")],
        )
        self.assertEqual(coordinator.ui_state_manager.active_page_uid, "p2")
        self.assertEqual(coordinator.opengl_viewer.plan_texture_update_calls, 1)
        self.assertEqual(coordinator._mesh_window.plan_texture_update_calls, 1)
        self.assertEqual(interaction_cancellations, ["cancel"])

    def test_clearing_active_page_clears_stale_page_settings_projection(self):
        coordinator, _pages = self._make_view_state_coordinator()
        page_settings_clears = []
        coordinator._page_settings_bar = SimpleNamespace(
            clear_page=lambda: page_settings_clears.append(True)
        )
        coordinator._prepare_plan_for_authoritative_refresh = lambda: None
        coordinator._save_current_page_view_state = lambda **_kwargs: None
        coordinator._viewer = SimpleNamespace(clear_plan_view=lambda: None)
        coordinator._sidebar = SimpleNamespace(
            update_conditions_quantities=lambda: None
        )
        coordinator._placement = SimpleNamespace(is_active=False)
        coordinator._sync_page_info_status = lambda: None
        coordinator._update_export_menu_state = lambda: None
        coordinator.handle_active_page_changed(None)
        self.assertEqual(page_settings_clears, [True])

    def test_missing_selected_page_cancels_pending_bid_selected_page_write(self):
        coordinator, _pages = self._make_view_state_coordinator()
        coordinator._save_current_page_view_state(selected_page_override="missing")
        self.assertEqual(coordinator._deferred_persistence.selected_page_calls, [])
        self.assertEqual(
            coordinator._deferred_persistence.cancel_bid_selected_pages_calls,
            [("a.mdb", ["bid-1"])],
        )

    def test_active_page_switch_recovers_stale_placement_cursor_mismatch(self):
        coordinator, _pages = self._make_view_state_coordinator()
        coordinator.plan_view.cursor_mode = "rotate"
        coordinator._update_page_settings_bar = lambda _page_uid: None
        coordinator._sync_overlay_display_mode = lambda _page_uid: None
        coordinator._update_plan_view = lambda _page_uid: None
        coordinator._sidebar = SimpleNamespace(
            update_conditions_quantities=lambda: None
        )
        force_exit_calls = []
        coordinator._placement = SimpleNamespace(
            is_active=True,
            force_exit=lambda: force_exit_calls.append("force_exit"),
        )
        coordinator._sync_page_info_status = lambda: None
        coordinator._update_export_menu_state = lambda: None
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        with self.assertLogs(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator",
            level="WARNING",
        ) as logs:
            coordinator.handle_active_page_changed("p2")
        self.assertEqual(force_exit_calls, ["force_exit"])
        self.assertEqual(coordinator.ui_state_manager.active_page_uid, "p2")
        self.assertIn("stale placement state", logs.output[0])

    def test_overlay_display_mode_captures_current_camera_before_reload(self):
        coordinator, pages = self._make_view_state_coordinator()
        calls = []
        coordinator.main_window = SimpleNamespace(
            refresh_detached_plan_views=lambda: calls.append("detached")
        )
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        coordinator._sync_overlay_display_mode = lambda page_uid: calls.append(
            ("sync", page_uid, pages[page_uid].zoom_fac)
        )
        coordinator._update_plan_view = lambda page_uid: calls.append(
            ("update", page_uid, pages[page_uid].zoom_fac)
        )
        coordinator._update_export_menu_state = lambda: calls.append("export")
        coordinator._on_overlay_display_mode_requested(2)
        self.assertEqual(pages["p1"].image_show_mode, 2)
        self.assertEqual(pages["p1"].zoom_fac, 2.5)
        self.assertEqual(pages["p1"].current_x, 10.0)
        self.assertEqual(pages["p1"].current_y, 20.0)
        self.assertEqual(
            coordinator._deferred_persistence.page_view_calls,
            [("a.mdb", "bid-1", "p1", 2.5, 10.0, 20.0)],
        )
        self.assertEqual(
            coordinator._deferred_persistence.selected_page_calls,
            [("a.mdb", "bid-1", "p1")],
        )
        self.assertEqual(
            coordinator._deferred_persistence.page_show_mode_calls,
            [("a.mdb", "p1", 2)],
        )
        self.assertEqual(
            calls,
            [("sync", "p1", 2.5), ("update", "p1", 2.5), "detached", "export"],
        )

    def test_overlay_display_failure_restores_only_originating_page(self):
        coordinator, pages = self._make_view_state_coordinator()
        pages["p1"].image_show_mode = 0
        coordinator.main_window = SimpleNamespace(
            refresh_detached_plan_views=lambda: None
        )
        coordinator._sync_overlay_display_mode = lambda _page_uid: None
        coordinator._update_plan_view = lambda _page_uid: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._on_overlay_display_mode_requested(2)
        callbacks = coordinator._deferred_persistence.page_show_mode_callbacks[0]
        callbacks["restore_authoritative"]()
        self.assertEqual(pages["p1"].image_show_mode, 0)
        coordinator.ui_state_manager.active_page_uid = "p2"
        callbacks["project_value"]()
        self.assertEqual(pages["p1"].image_show_mode, 2)

    def test_page_visual_completion_does_not_touch_cleaned_up_coordinator(self):
        coordinator, _pages = self._make_view_state_coordinator()
        coordinator.main_window = SimpleNamespace(
            refresh_detached_plan_views=lambda: None
        )
        coordinator._sync_overlay_display_mode = lambda _page_uid: None
        coordinator._update_plan_view = lambda _page_uid: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._on_overlay_display_mode_requested(2)
        callbacks = coordinator._deferred_persistence.page_show_mode_callbacks[0]
        coordinator._is_cleaning_up = True
        coordinator.ui_state_manager = None
        coordinator.project_data = None
        callbacks["restore_authoritative"]()
        callbacks["project_value"]()

    def test_page_visual_completion_rejects_same_uid_page_replacement(self):
        coordinator, pages = self._make_view_state_coordinator()
        coordinator.main_window = SimpleNamespace(
            refresh_detached_plan_views=lambda: None
        )
        coordinator._sync_overlay_display_mode = lambda _page_uid: None
        coordinator._update_plan_view = lambda _page_uid: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._on_overlay_display_mode_requested(2)
        callbacks = coordinator._deferred_persistence.page_show_mode_callbacks[0]
        replacement = Page(uid="p1", name="replacement", image_show_mode=1)
        pages["p1"] = replacement
        callbacks["restore_authoritative"]()
        callbacks["project_value"]()
        self.assertEqual(replacement.image_show_mode, 1)

    def test_page_visual_failure_restores_inactive_originating_page_model(self):
        coordinator, pages = self._make_view_state_coordinator()
        pages["p1"].image_show_mode = 0
        coordinator.main_window = SimpleNamespace(
            refresh_detached_plan_views=lambda: None
        )
        coordinator._sync_overlay_display_mode = lambda _page_uid: None
        coordinator._update_plan_view = lambda _page_uid: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._on_overlay_display_mode_requested(2)
        callbacks = coordinator._deferred_persistence.page_show_mode_callbacks[0]
        coordinator.ui_state_manager.active_page_uid = "p2"
        callbacks["restore_authoritative"]()
        self.assertEqual(pages["p1"].image_show_mode, 0)

    def test_rejected_page_visual_schedule_does_not_leave_optimistic_state(self):
        coordinator, pages = self._make_view_state_coordinator()
        pages["p1"].image_show_mode = 0
        coordinator.main_window = SimpleNamespace(
            refresh_detached_plan_views=lambda: None
        )
        coordinator._sync_overlay_display_mode = lambda _page_uid: None
        coordinator._update_plan_view = lambda _page_uid: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._deferred_persistence.schedule_page_show_mode = (
            lambda *_args, **_kwargs: False
        )
        coordinator._on_overlay_display_mode_requested(2)
        self.assertEqual(pages["p1"].image_show_mode, 0)

    def test_page_image_flag_failure_restores_main_and_detached_views(self):
        coordinator, pages = self._make_view_state_coordinator()
        page = pages["p1"]
        page.invert = False
        updates = []
        coordinator.main_window = SimpleNamespace(
            refresh_detached_plan_views=lambda: updates.append("detached")
        )
        coordinator._update_plan_view = lambda page_uid: updates.append(page_uid)
        coordinator._update_export_menu_state = lambda: updates.append("export")
        coordinator.toggle_page_invert(True)
        callbacks = coordinator._deferred_persistence.page_invert_callbacks[0]
        callbacks["restore_authoritative"]()
        self.assertFalse(page.invert)
        self.assertEqual(
            updates,
            ["p1", "detached", "export", "p1", "detached", "export"],
        )
        coordinator.ui_state_manager.active_page_uid = "p2"
        callbacks["project_value"]()
        self.assertTrue(page.invert)
        self.assertEqual(updates[-1], "detached")

    def test_overlay_visibility_cannot_select_or_hide_the_only_source(self):
        coordinator, pages = self._make_view_state_coordinator()
        page = pages["p1"]
        transitions = []
        coordinator._on_overlay_display_mode_requested = (
            lambda mode: transitions.append(mode)
        )
        coordinator._update_export_menu_state = lambda: None
        page.image_path = ""
        page.overlay_image_path = "overlay.pdf"
        page.image_show_mode = 1
        coordinator.show_original_image(True)
        coordinator.show_overlay_image(False)
        page.image_path = "original.pdf"
        page.overlay_image_path = ""
        page.image_show_mode = 0
        coordinator.show_overlay_image(True)
        coordinator.show_original_image(False)
        self.assertEqual(transitions, [])

    def test_close_captures_latest_page_view_and_selected_page_writes(self):
        coordinator, _pages = self._make_view_state_coordinator()
        coordinator.capture_current_page_state_for_shutdown()
        self.assertEqual(
            coordinator._deferred_persistence.page_view_calls,
            [("a.mdb", "bid-1", "p1", 2.5, 10.0, 20.0)],
        )
        self.assertEqual(
            coordinator._deferred_persistence.selected_page_calls,
            [("a.mdb", "bid-1", "p1")],
        )

    def test_failed_close_time_page_view_is_terminal_without_warning(self):
        service = FakeProjectWriteService()
        service.fail_methods.add("save_page_view_state")
        logger = logging.getLogger("tests.failed_close_time_page_view")
        manager = DeferredPersistenceManager(
            service, _workspace_service(service), logger_=logger
        )
        self.addCleanup(manager.cleanup)
        self.addCleanup(lambda: service.fail_methods.clear())
        manager.schedule_page_view_state("a.mdb", "b1", "p1", 2.0, 10.0, 20.0)
        with self.assertNoLogs(logger, level="WARNING"):
            self.assertTrue(manager.flush())
            self.assertTrue(manager.flush())
        self.assertEqual(manager.pending_count, 0)
        self.assertEqual(
            service.calls,
            [("page_view_state", "a.mdb", "p1", 2.0, 10.0, 20.0)],
        )

    def _make_visibility_coordinator(
        self,
        *,
        layer_name="Layer 1",
        selected_page_uids=None,
        active_page_uid="p1",
        condition_layer_uid="l1",
        page_layer_uid=None,
    ):
        selected_page_uids = selected_page_uids or [active_page_uid]
        page_layer_uid = (
            "l1" if page_layer_uid is None and layer_name == "Image" else page_layer_uid
        )
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: False
        )
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("a.mdb", "bid-1"),
            active_page_uid=active_page_uid,
            place_condition_uid=None,
            place_condition_uids=[],
            state=SimpleNamespace(grayscale_enabled=False),
        )
        pages = {
            "p1": Page(uid="p1", name="P1"),
            "p2": Page(uid="p2", name="P2"),
        }
        conditions = {
            "c1": Condition(uid="c1", name="C1", layer_uid=condition_layer_uid),
        }
        layers = [
            SimpleNamespace(uid="l1", name=layer_name, show=True),
            SimpleNamespace(uid="other", name="Other", show=True),
            SimpleNamespace(uid="annotation-layer", name="Annotation", show=True),
        ]
        annotation_layer_uid = "annotation-layer"
        bid_owner = object()
        coordinator.quantity_update_calls = []
        quantity_calls = coordinator.quantity_update_calls

        def is_page_layer_uid(layer_uid):
            return page_layer_uid is not None and str(layer_uid) == str(page_layer_uid)

        def update_layer_visibility(layer_uid, show):
            for layer in layers:
                if str(layer.uid) == str(layer_uid):
                    layer.show = bool(show)
            if not is_page_layer_uid(layer_uid):
                return []
            for page in pages.values():
                page.layer_visible = bool(show)
            return ["p1", "p2"]

        def update_all_layer_visibility(show):
            for page in pages.values():
                page.layer_visible = bool(show)
            return ["p1", "p2"]

        coordinator.project_data = SimpleNamespace(
            is_image_layer_uid=is_page_layer_uid,
            update_layer_visibility=update_layer_visibility,
            update_all_layer_visibility=update_all_layer_visibility,
            set_bid_layer_visibility=lambda _layers: None,
            get_hidden_layer_uids=lambda: set(),
            is_annotation_layer_visible=lambda: True,
            get_selected_page_uids=lambda: list(selected_page_uids),
            get_bid=lambda _bid_ref: bid_owner,
            get_page=lambda page_uid: pages.get(page_uid),
            get_bid_layer_snapshot=lambda: list(layers),
            get_bid_conditions=lambda: conditions,
            get_annotation_layer_uid=lambda: annotation_layer_uid,
        )
        coordinator._project_read_service = SimpleNamespace(
            get_merged_bid_layers=lambda _db_path, _bid_uid: list(layers)
        )
        coordinator._sidebar = SimpleNamespace(
            bid_layers_sidebar=SimpleNamespace(
                get_layer=lambda _uid: layers[0],
                get_layers=lambda: list(layers),
                get_layer_visibility=lambda layer_uid: next(
                    (
                        bool(layer.show)
                        for layer in layers
                        if str(layer.uid) == str(layer_uid)
                    ),
                    None,
                ),
                set_layer_visible=lambda layer_uid, show: [
                    setattr(layer, "show", bool(show))
                    for layer in layers
                    if str(layer.uid) == str(layer_uid)
                ],
                set_all_layers_visible=lambda show: [
                    setattr(layer, "show", bool(show)) for layer in layers
                ],
            ),
            update_conditions_quantities=lambda: quantity_calls.append("quantity"),
            load_condition_summary=lambda: None,
        )
        coordinator.conditions_sidebar = None
        coordinator.condition_summary_tab = None
        coordinator.layer_events = []
        coordinator.event_bus = SimpleNamespace(
            publish=lambda event, **event_payload: coordinator.layer_events.append(
                (event, event_payload)
            )
        )
        coordinator._viewer = SimpleNamespace(update_viewers=lambda page_uids: None)
        coordinator._update_plan_view_calls = []
        coordinator._update_plan_view = (
            lambda page_uid: coordinator._update_plan_view_calls.append(page_uid)
        )
        coordinator._update_export_menu_state = lambda: None
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )

        def enter_place(condition_uid, _selected):
            coordinator.plan_view.cursor_mode = "place"
            coordinator.plan_view.place_condition_uid = condition_uid
            coordinator.ui_state_manager.place_condition_uid = condition_uid
            coordinator.ui_state_manager.place_condition_uids = list(_selected)
            return True

        coordinator._placement = SimpleNamespace(enter=enter_place)
        coordinator.select_checked_calls = []
        coordinator.toolbar_refresh_calls = []
        coordinator._toolbar = SimpleNamespace(
            refresh=lambda: coordinator.toolbar_refresh_calls.append("refresh"),
            set_select_checked=lambda: coordinator.select_checked_calls.append(
                "select"
            ),
            is_takeoff_2d_view_active=lambda: True,
        )
        coordinator._suspended_layer_tool = None
        coordinator.plan_view = RecordingPlanView()
        coordinator._deferred_persistence = RecordingDeferredPersistence()
        coordinator._visibility_test_layers = layers
        self._install_hidden_2d_mesh_state(coordinator)
        return coordinator

    def _install_conditions_sidebar_recorder(self, coordinator):
        calls = []
        coordinator.conditions_sidebar = SimpleNamespace(
            apply_layer_visibility_state=(
                lambda conditions, grayscale, layer_uid=None: calls.append(
                    ("apply", list(conditions), grayscale, layer_uid)
                )
            ),
            load_conditions=lambda _conditions, _folders, _project_name, grayscale=False: self.fail(
                "visibility-only toggle should not reload condition tree"
            ),
        )
        return calls

    def test_show_all_without_sidebar_queues_all_layers_from_read_service(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        bid_owner = object()
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: False
        )
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("a.mdb", "bid-1"),
            active_page_uid="p1",
            state=SimpleNamespace(grayscale_enabled=False),
        )
        coordinator.project_data = SimpleNamespace(
            update_all_layer_visibility=lambda _show: ["p1"],
            set_bid_layer_visibility=lambda _layers: None,
            get_hidden_layer_uids=lambda: set(),
            is_annotation_layer_visible=lambda: True,
            get_selected_page_uids=lambda: ["p1"],
            get_bid=lambda _bid_ref: bid_owner,
            get_page=lambda _page_uid: None,
            get_bid_conditions=lambda: {},
            get_annotation_layer_uid=lambda: "annotation-layer",
        )
        coordinator._project_read_service = SimpleNamespace(
            get_merged_bid_layers=lambda _db_path, _bid_uid: [
                SimpleNamespace(uid="l1", show=True),
                SimpleNamespace(uid="l2", show=True),
            ]
        )
        quantity_calls = []
        coordinator._sidebar = SimpleNamespace(
            bid_layers_sidebar=None,
            update_conditions_quantities=lambda: quantity_calls.append("quantity"),
            load_condition_summary=lambda: None,
        )
        coordinator.conditions_sidebar = None
        coordinator.condition_summary_tab = None
        coordinator.event_bus = SimpleNamespace(
            publish=lambda *_args, **_call_options: None
        )
        coordinator.plan_view = None
        self._install_hidden_2d_mesh_state(coordinator)
        coordinator._viewer = SimpleNamespace(update_viewers=lambda _page_uids: None)
        coordinator._update_plan_view = lambda _page_uid: None
        coordinator._update_export_menu_state = lambda: None
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )

        def enter_place(_condition_uid, _selected):
            return False

        coordinator._placement = SimpleNamespace(enter=enter_place)
        coordinator._toolbar = SimpleNamespace(
            refresh=lambda: None,
            set_select_checked=lambda: None,
            is_takeoff_2d_view_active=lambda: True,
        )
        coordinator._suspended_layer_tool = None
        deferred = RecordingDeferredPersistence()
        coordinator._deferred_persistence = deferred
        self.assertTrue(coordinator.update_all_layers_visibility_deferred(False))
        self.assertEqual(
            deferred.all_layer_calls,
            [("a.mdb", "bid-1", False, ["l1", "l2"])],
        )
        self.assertEqual(coordinator.mesh_refresh_calls, [])
        self.assertTrue(coordinator._mesh_scene_dirty)
        self.assertEqual(coordinator._dirty_mesh_page_uids, {"p1"})
        self.assertEqual(quantity_calls, [])

    def test_sql_show_all_without_sidebar_uses_hydrated_layers(self):
        coordinator = self._make_visibility_coordinator()
        coordinator._sidebar.bid_layers_sidebar = None
        coordinator._sidebar.load_condition_summary_from_memory = lambda: None
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: True
        )
        coordinator.project_data.get_bid_layer_snapshot = lambda: [
            SimpleNamespace(uid="l1", name="Layer 1", show=True),
            SimpleNamespace(uid="l2", name="Layer 2", show=True),
        ]
        coordinator._project_read_service.get_merged_bid_layers = (
            lambda _db_path, _bid_uid: self.fail(
                "SQL layer projection must not query the database on the Qt thread"
            )
        )
        self.assertTrue(coordinator.update_all_layers_visibility_deferred(False))
        self.assertEqual(
            coordinator._deferred_persistence.all_layer_calls,
            [("a.mdb", "bid-1", False, ["l1", "l2"])],
        )

    def test_bulk_layer_visibility_already_at_requested_state_is_a_no_op(self):
        coordinator = self._make_visibility_coordinator()
        self.assertTrue(coordinator.update_all_layers_visibility_deferred(True))
        self.assertEqual(coordinator._deferred_persistence.all_layer_calls, [])
        self.assertEqual(coordinator.layer_events, [])

    def test_repeated_same_bulk_intent_is_retained_while_first_write_is_pending(self):
        coordinator = self._make_visibility_coordinator()
        self.assertTrue(coordinator.update_all_layers_visibility_deferred(False))
        self.assertTrue(coordinator.update_all_layers_visibility_deferred(False))
        self.assertEqual(
            coordinator._deferred_persistence.all_layer_calls,
            [
                (
                    "a.mdb",
                    "bid-1",
                    False,
                    ["l1", "other", "annotation-layer"],
                ),
                (
                    "a.mdb",
                    "bid-1",
                    False,
                    ["l1", "other", "annotation-layer"],
                ),
            ],
        )

    def test_bulk_layer_visibility_with_no_layers_does_not_queue_a_write(self):
        coordinator = self._make_visibility_coordinator()
        coordinator._visibility_test_layers.clear()
        self.assertFalse(coordinator.update_all_layers_visibility_deferred(False))
        self.assertEqual(coordinator._deferred_persistence.all_layer_calls, [])
        self.assertEqual(coordinator.layer_events, [])

    def test_rejected_deferred_schedule_does_not_leave_optimistic_visibility(self):
        coordinator = self._make_visibility_coordinator()
        original = [layer.show for layer in coordinator._visibility_test_layers]
        coordinator._deferred_persistence = SimpleNamespace(
            has_all_layers_show_revision=lambda *_args: False,
            schedule_all_layers_show=lambda *_args, **_kwargs: False,
            schedule_layer_show=lambda *_args, **_kwargs: False,
        )
        self.assertFalse(coordinator.update_all_layers_visibility_deferred(False))
        self.assertEqual(
            [layer.show for layer in coordinator._visibility_test_layers], original
        )
        self.assertEqual(coordinator.layer_events, [])
        self.assertFalse(coordinator.update_layer_visibility_deferred("l1", False))
        self.assertEqual(
            [layer.show for layer in coordinator._visibility_test_layers], original
        )
        self.assertEqual(coordinator.layer_events, [])

    def test_rejected_individual_schedule_restores_clicked_checkbox(self):
        coordinator = self._make_visibility_coordinator()
        layers = coordinator._visibility_test_layers
        layers[:] = [BidLayer("l1", "bid-1", "Layer 1", True, 1)]
        sidebar = BidLayersSidebar(None)
        sidebar.load_layers(layers)
        sidebar.set_toggle_callback(coordinator.update_layer_visibility_deferred)
        coordinator._sidebar.bid_layers_sidebar = sidebar
        coordinator._deferred_persistence = SimpleNamespace(
            schedule_layer_show=lambda *_args, **_kwargs: False,
        )
        try:
            sidebar._checkboxes[0].click()
            self.assertTrue(sidebar._checkboxes[0].isChecked())
            self.assertTrue(layers[0].show)
            self.assertEqual(coordinator.layer_events, [])
        finally:
            sidebar.close()
            sidebar.deleteLater()

    def test_image_layer_disable_queues_write_and_does_not_reload_pages(self):
        coordinator = self._make_visibility_coordinator(
            layer_name="Image",
            condition_layer_uid="other-layer",
        )
        self._install_native_mesh_recorders(coordinator)
        mesh_calls = []
        coordinator._viewer = SimpleNamespace(
            update_viewers=lambda page_uids: mesh_calls.append(page_uids)
        )
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        self.assertEqual(
            coordinator._deferred_persistence.layer_calls,
            [("a.mdb", "l1", False)],
        )
        self.assertEqual(coordinator._update_plan_view_calls, [])
        self.assertEqual(coordinator.plan_view.image_visibility_pages, ["p1"])
        self.assertEqual(mesh_calls, [])
        self.assertEqual(coordinator.quantity_update_calls, [])
        self.assertEqual(coordinator.opengl_viewer.plan_texture_update_calls, 1)
        self.assertEqual(coordinator._mesh_window.plan_texture_update_calls, 1)
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", True))
        self.assertEqual(mesh_calls, [])
        self.assertEqual(coordinator.opengl_viewer.plan_texture_update_calls, 2)
        self.assertEqual(coordinator._mesh_window.plan_texture_update_calls, 2)

    def test_condition_layer_visibility_uses_loaded_item_path(self):
        coordinator = self._make_visibility_coordinator(layer_name="Layer 1")
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        self.assertEqual(coordinator._update_plan_view_calls, [])
        self.assertEqual(len(coordinator.plan_view.layer_visibility_calls), 1)
        self.assertEqual(coordinator.mesh_refresh_calls, [])
        self.assertTrue(coordinator._mesh_scene_dirty)
        self.assertEqual(coordinator._dirty_mesh_page_uids, {"p1"})
        self.assertEqual(coordinator.quantity_update_calls, [])

    def test_layer_visibility_updates_conditions_sidebar_without_full_reload(self):
        coordinator = self._make_visibility_coordinator(layer_name="Layer 1")
        calls = self._install_conditions_sidebar_recorder(coordinator)
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        self.assertEqual(calls, [("apply", ["c1"], False, "l1")])

    def test_layers_without_condition_rows_skip_conditions_sidebar_refresh(self):
        for layer_name in ("Annotation", "Image", "Future Visual", "Custom Empty"):
            with self.subTest(layer_name=layer_name):
                coordinator = self._make_visibility_coordinator(
                    layer_name=layer_name,
                    condition_layer_uid="other-layer",
                )
                calls = self._install_conditions_sidebar_recorder(coordinator)
                self.assertTrue(
                    coordinator.update_layer_visibility_deferred("l1", False)
                )
                self.assertEqual(calls, [])
                self.assertEqual(coordinator.mesh_refresh_calls, [])
                self.assertEqual(coordinator.quantity_update_calls, [])

    def test_layer_visibility_uses_same_deferred_path_for_all_layer_names(self):
        cases = (
            ("Annotation", False),
            ("Image", True),
            ("Future Visual", False),
            ("Custom Empty", False),
        )
        for layer_name, page_layer_changed in cases:
            with self.subTest(layer_name=layer_name):
                coordinator = self._make_visibility_coordinator(
                    layer_name=layer_name,
                    condition_layer_uid="other-layer",
                )
                self.assertTrue(
                    coordinator.update_layer_visibility_deferred("l1", False)
                )
                self.assertEqual(
                    coordinator._deferred_persistence.layer_calls,
                    [("a.mdb", "l1", False)],
                )
                self.assertEqual(
                    coordinator.layer_events[0][1]["layer_uid"],
                    "l1",
                )
                if page_layer_changed:
                    self.assertEqual(
                        coordinator.plan_view.image_visibility_pages, ["p1"]
                    )
                    self.assertEqual(coordinator.plan_view.layer_visibility_calls, [])
                else:
                    self.assertEqual(coordinator.plan_view.image_visibility_pages, [])
                    self.assertEqual(
                        len(coordinator.plan_view.layer_visibility_calls),
                        1,
                    )

    def test_condition_layer_without_condition_rows_skips_conditions_sidebar_refresh(
        self,
    ):
        coordinator = self._make_visibility_coordinator(
            layer_name="Layer 1",
            condition_layer_uid="other-layer",
        )
        calls = self._install_conditions_sidebar_recorder(coordinator)
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        self.assertEqual(calls, [])
        self.assertEqual(coordinator.quantity_update_calls, [])

    def test_default_named_layer_with_condition_rows_refreshes_conditions_sidebar(self):
        coordinator = self._make_visibility_coordinator(layer_name="Annotation")
        calls = self._install_conditions_sidebar_recorder(coordinator)
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        self.assertEqual(calls, [("apply", ["c1"], False, "l1")])
        self.assertEqual(coordinator.quantity_update_calls, [])

    def test_repeated_layer_toggles_refresh_view_immediately(self):
        coordinator = self._make_visibility_coordinator(layer_name="Layer 1")
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", True))
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        self.assertEqual(coordinator.quantity_update_calls, [])
        self.assertEqual(coordinator.mesh_refresh_calls, [])
        self.assertTrue(coordinator._mesh_scene_dirty)
        self.assertEqual(coordinator._dirty_mesh_page_uids, {"p1"})

    def test_layer_visibility_failure_restores_only_originating_bid(self):
        coordinator = self._make_visibility_coordinator(layer_name="Layer 1")
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        callbacks = coordinator._deferred_persistence.layer_callbacks[0]
        callbacks["restore_authoritative"]()
        self.assertTrue(coordinator.project_data.get_bid_layer_snapshot()[0].show)
        coordinator.ui_state_manager.get_selected_bid_ref = lambda: BidRef(
            "a.mdb", "bid-2"
        )
        callbacks["project_value"]()
        self.assertTrue(coordinator.project_data.get_bid_layer_snapshot()[0].show)

    def test_individual_layer_completion_rejects_same_uid_bid_replacement(self):
        coordinator = self._make_visibility_coordinator(layer_name="Layer 1")
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        callbacks = coordinator._deferred_persistence.layer_callbacks[0]
        event_count = len(coordinator.layer_events)
        coordinator.project_data.get_bid = lambda _bid_ref: object()
        callbacks["restore_authoritative"]()
        callbacks["project_value"]()
        self.assertEqual(len(coordinator.layer_events), event_count)

    def test_individual_layer_completion_does_not_duplicate_current_projection(self):
        coordinator = self._make_visibility_coordinator(layer_name="Layer 1")
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        callbacks = coordinator._deferred_persistence.layer_callbacks[0]
        event_count = len(coordinator.layer_events)
        callbacks["project_value"]()
        self.assertEqual(len(coordinator.layer_events), event_count)

    def test_layer_completion_does_not_touch_cleaned_up_coordinator(self):
        coordinator = self._make_visibility_coordinator(layer_name="Layer 1")
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        callbacks = coordinator._deferred_persistence.layer_callbacks[0]
        coordinator._is_cleaning_up = True
        coordinator.ui_state_manager = None
        coordinator.project_data = None
        self.assertFalse(callbacks["restore_authoritative"]())
        self.assertFalse(callbacks["project_value"]())
        bulk_coordinator = self._make_visibility_coordinator(layer_name="Layer 1")
        self.assertTrue(bulk_coordinator.update_all_layers_visibility_deferred(False))
        bulk_callbacks = bulk_coordinator._deferred_persistence.all_layer_callbacks[0]
        bulk_coordinator._is_cleaning_up = True
        bulk_coordinator.ui_state_manager = None
        bulk_coordinator.project_data = None
        self.assertFalse(bulk_callbacks["restore_authoritative"]())
        self.assertFalse(bulk_callbacks["project_value"]())

    def test_layer_completion_does_not_touch_destroyed_sidebar(self):
        from shiboken6 import delete

        for bulk in (False, True):
            with self.subTest(bulk=bulk):
                coordinator = self._make_visibility_coordinator(layer_name="Layer 1")
                coordinator._visibility_test_layers[:] = [
                    BidLayer("l1", "bid-1", "Layer 1", True, 1),
                    BidLayer("other", "bid-1", "Other", True, 2),
                ]
                sidebar = BidLayersSidebar(None)
                sidebar.load_layers(coordinator._visibility_test_layers)
                coordinator._sidebar.bid_layers_sidebar = sidebar
                if bulk:
                    self.assertTrue(
                        coordinator.update_all_layers_visibility_deferred(False)
                    )
                    callbacks = coordinator._deferred_persistence.all_layer_callbacks[0]
                else:
                    self.assertTrue(
                        coordinator.update_layer_visibility_deferred("l1", False)
                    )
                    callbacks = coordinator._deferred_persistence.layer_callbacks[0]
                delete(sidebar)
                self.assertTrue(callbacks["project_value"]())

    def test_bulk_layer_completion_does_not_project_after_bid_switch(self):
        coordinator = self._make_visibility_coordinator(layer_name="Layer 1")
        self.assertTrue(coordinator.update_all_layers_visibility_deferred(False))
        callbacks = coordinator._deferred_persistence.all_layer_callbacks[0]
        event_count = len(coordinator.layer_events)
        coordinator.ui_state_manager.get_selected_bid_ref = lambda: BidRef(
            "a.mdb", "bid-2"
        )
        callbacks["restore_authoritative"]()
        callbacks["project_value"]()
        self.assertEqual(len(coordinator.layer_events), event_count)

    def test_bulk_layer_completion_rejects_same_uid_bid_replacement(self):
        coordinator = self._make_visibility_coordinator(layer_name="Layer 1")
        self.assertTrue(coordinator.update_all_layers_visibility_deferred(False))
        callbacks = coordinator._deferred_persistence.all_layer_callbacks[0]
        event_count = len(coordinator.layer_events)
        coordinator.project_data.get_bid = lambda _bid_ref: object()
        callbacks["restore_authoritative"]()
        callbacks["project_value"]()
        self.assertEqual(len(coordinator.layer_events), event_count)

    def test_bulk_layer_visibility_rejects_missing_authoritative_bid_owner(self):
        coordinator = self._make_visibility_coordinator(layer_name="Layer 1")
        coordinator.project_data.get_bid = lambda _bid_ref: None
        original = [layer.show for layer in coordinator._visibility_test_layers]
        self.assertFalse(coordinator.update_all_layers_visibility_deferred(False))
        self.assertEqual(
            [layer.show for layer in coordinator._visibility_test_layers], original
        )
        self.assertEqual(coordinator._deferred_persistence.all_layer_calls, [])
        self.assertEqual(coordinator.layer_events, [])

    def test_bulk_layer_recovery_uses_the_production_event_contract(self):
        coordinator = self._make_visibility_coordinator(layer_name="Layer 1")
        events = []
        event_bus = EventBus()
        event_bus.subscribe(
            AppEvents.LAYER_VISIBILITY_CHANGED,
            lambda **payload: events.append(payload),
        )
        coordinator.event_bus = event_bus
        coordinator._sidebar.bid_layers_sidebar.set_layer_visibilities = (
            lambda _map: None
        )
        self.assertTrue(coordinator.update_all_layers_visibility_deferred(False))
        callbacks = coordinator._deferred_persistence.all_layer_callbacks[0]
        callbacks["restore_authoritative"]()
        self.assertEqual(len(events), 2)
        self.assertTrue(events[-1]["all_layers"])

    def test_layer_visibility_failure_does_not_restore_deleted_layer(self):
        coordinator = self._make_visibility_coordinator(layer_name="Layer 1")
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        callbacks = coordinator._deferred_persistence.layer_callbacks[0]
        event_count = len(coordinator.layer_events)
        coordinator._visibility_test_layers[:] = [
            layer for layer in coordinator._visibility_test_layers if layer.uid != "l1"
        ]
        self.assertFalse(callbacks["restore_authoritative"]())
        self.assertEqual(len(coordinator.layer_events), event_count)

    def test_hiding_annotation_layer_temporarily_selects_then_restores_tool(self):
        coordinator = self._make_visibility_coordinator(
            layer_name="Annotation",
            condition_layer_uid="condition-layer",
        )
        coordinator.plan_view.cursor_mode = "annotation_place"
        coordinator.plan_view.annotation_place_type = ANNOTATION_TYPE_RECT
        self.assertTrue(
            coordinator.update_layer_visibility_deferred("annotation-layer", False)
        )
        self.assertEqual(coordinator.plan_view.cursor_mode, "select")
        self.assertEqual(coordinator.plan_view.cursor_modes, ["select"])
        self.assertEqual(coordinator.select_checked_calls, ["select"])
        self.assertTrue(
            coordinator.update_layer_visibility_deferred("annotation-layer", True)
        )
        self.assertEqual(coordinator.plan_view.cursor_mode, "annotation_place")
        self.assertEqual(
            coordinator.plan_view.annotation_placements, [ANNOTATION_TYPE_RECT]
        )

    def test_hiding_unrelated_layer_keeps_active_annotation_tool(self):
        coordinator = self._make_visibility_coordinator(
            layer_name="Layer 1",
            condition_layer_uid="condition-layer",
        )
        coordinator.plan_view.cursor_mode = "annotation_place"
        coordinator.plan_view.annotation_place_type = ANNOTATION_TYPE_RECT
        self.assertTrue(coordinator.update_layer_visibility_deferred("other", False))
        self.assertEqual(coordinator.plan_view.cursor_mode, "annotation_place")
        self.assertEqual(
            coordinator.plan_view.annotation_place_type, ANNOTATION_TYPE_RECT
        )
        self.assertEqual(coordinator.plan_view.cursor_modes, [])
        self.assertEqual(coordinator.select_checked_calls, [])

    def test_hiding_condition_layer_temporarily_selects_then_restores_place_tool(self):
        coordinator = self._make_visibility_coordinator(layer_name="Layer 1")
        coordinator.plan_view.cursor_mode = "place"
        coordinator.plan_view.place_condition_uid = "c1"
        coordinator.ui_state_manager.place_condition_uid = "c1"
        coordinator.ui_state_manager.place_condition_uids = ["c1"]
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        self.assertEqual(coordinator.plan_view.cursor_mode, "select")
        self.assertEqual(coordinator.plan_view.cursor_modes, ["select"])
        self.assertEqual(coordinator.select_checked_calls, ["select"])
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", True))
        self.assertEqual(coordinator.plan_view.cursor_mode, "place")
        self.assertEqual(coordinator.plan_view.place_condition_uid, "c1")

    def test_showing_layer_rejects_suspended_same_uid_condition_replacement(self):
        coordinator = self._make_visibility_coordinator(layer_name="Layer 1")
        coordinator.plan_view.cursor_mode = "place"
        coordinator.plan_view.place_condition_uid = "c1"
        coordinator.ui_state_manager.place_condition_uid = "c1"
        coordinator.ui_state_manager.place_condition_uids = ["c1"]
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        coordinator.project_data.get_bid_conditions()["c1"] = Condition(
            uid="c1",
            name="Replacement",
            layer_uid="l1",
            layer_visible=True,
        )
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", True))
        self.assertEqual(coordinator.plan_view.cursor_mode, "select")
        self.assertIsNone(coordinator.plan_view.place_condition_uid)

    def test_hide_all_temporarily_selects_then_show_all_restores_annotation_tool(self):
        coordinator = self._make_visibility_coordinator(
            layer_name="Annotation",
            condition_layer_uid="condition-layer",
        )
        coordinator.plan_view.cursor_mode = "annotation_place"
        coordinator.plan_view.annotation_place_type = ANNOTATION_TYPE_TEXT
        self.assertTrue(coordinator.update_all_layers_visibility_deferred(False))
        self.assertEqual(coordinator.plan_view.cursor_mode, "select")
        self.assertTrue(coordinator.update_all_layers_visibility_deferred(True))
        self.assertEqual(coordinator.plan_view.cursor_mode, "annotation_place")
        self.assertEqual(
            coordinator.plan_view.annotation_placements, [ANNOTATION_TYPE_TEXT]
        )

    def test_show_all_uses_shared_page_and_layer_visibility_refresh(self):
        coordinator = self._make_visibility_coordinator(layer_name="Image")
        self._install_native_mesh_recorders(coordinator)
        self.assertTrue(coordinator.update_all_layers_visibility_deferred(False))
        self.assertEqual(coordinator._update_plan_view_calls, [])
        self.assertEqual(coordinator.plan_view.image_visibility_pages, ["p1"])
        self.assertEqual(
            coordinator.plan_view.all_layer_visibility_calls,
            [(False, coordinator.project_data.get_bid_conditions())],
        )
        self.assertEqual(coordinator.plan_view.layer_visibility_calls, [])
        self.assertEqual(coordinator.opengl_viewer.plan_texture_update_calls, 1)
        self.assertTrue(coordinator.update_all_layers_visibility_deferred(True))
        self.assertEqual(coordinator.opengl_viewer.plan_texture_update_calls, 2)
        self.assertEqual(coordinator._mesh_window.plan_texture_update_calls, 2)

    def test_database_refresh_flushes_pending_visual_state_before_reload(self):
        calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        coordinator._deferred_persistence = SimpleNamespace(
            flush_for_file=lambda file_path: calls.append(("flush", file_path)) or True
        )
        coordinator._nav = SimpleNamespace(
            start_refresh=lambda _ui_state, _placement, selected_area_uid="": calls.append(
                "start"
            )
            or True
        )
        coordinator.ui_state_manager = SimpleNamespace(
            selected_area_uid="",
            selected_page_uids=[],
            get_selected_bid_ref=lambda: None,
        )
        coordinator._mesh_scene_dirty = False
        coordinator._placement = SimpleNamespace()
        coordinator._do_file_refresh = lambda: calls.append("refresh")
        coordinator._finish_refresh = lambda: calls.append("finish")
        coordinator._on_database_refreshed(file_path="a.mdb")
        self.assertEqual(calls, [("flush", "a.mdb"), "start", "refresh", "finish"])

    def test_external_access_refresh_discards_old_runtime_state_before_projection(self):
        calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator._deferred_persistence = SimpleNamespace(
            flush_for_file=lambda file_path: calls.append(("flush", file_path)) or True,
            cancel_for_file=lambda file_path: calls.append(("cancel", file_path)),
        )
        coordinator._undo_service = SimpleNamespace(
            clear=lambda: calls.append("clear-undo")
        )
        coordinator._prepare_for_modal_mutation_error = lambda file_path: calls.append(
            ("cancel-interactions", file_path)
        )
        coordinator._selected_takeoff_uids = ("stale-takeoff",)
        coordinator._sync_selection = lambda source, uids: calls.append(
            ("selection", source, list(uids))
        )
        coordinator.project_data = SimpleNamespace(
            get_current_file_path=lambda: "a.mdb"
        )
        coordinator._nav = SimpleNamespace(
            start_refresh=lambda _ui_state, _placement, selected_area_uid="": calls.append(
                "start"
            )
            or True
        )
        coordinator.ui_state_manager = SimpleNamespace(
            selected_area_uid="",
            selected_page_uids=[],
            get_selected_bid_ref=lambda: None,
        )
        coordinator._mesh_scene_dirty = False
        coordinator._placement = SimpleNamespace()
        coordinator._do_file_refresh = lambda: calls.append("refresh")
        coordinator._finish_refresh = lambda: calls.append("finish")
        coordinator._on_database_refreshed(
            file_path="a.mdb",
            external_change=True,
        )
        self.assertEqual(
            calls,
            [
                ("cancel", "a.mdb"),
                "clear-undo",
                ("cancel-interactions", "a.mdb"),
                ("selection", coordinator._SOURCE_MODEL, []),
                "start",
                "refresh",
                "finish",
            ],
        )

    def test_external_background_access_refresh_preserves_active_runtime_state(self):
        calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator._deferred_persistence = SimpleNamespace(
            cancel_for_file=lambda file_path: calls.append(("cancel", file_path)),
        )
        coordinator._undo_service = SimpleNamespace(
            clear=lambda: calls.append("clear-undo")
        )
        coordinator._prepare_for_modal_mutation_error = lambda file_path: calls.append(
            ("cancel-interactions", file_path)
        )
        coordinator._selected_takeoff_uids = ("active-takeoff",)
        coordinator._sync_selection = lambda source, uids: calls.append(
            ("selection", source, list(uids))
        )
        coordinator.project_data = SimpleNamespace(
            get_current_file_path=lambda: "active.mdb"
        )
        coordinator._nav = SimpleNamespace(
            start_refresh=lambda _ui_state, _placement, selected_area_uid="": calls.append(
                "start"
            )
            or True
        )
        coordinator.ui_state_manager = SimpleNamespace(
            selected_area_uid="",
            selected_page_uids=[],
            get_selected_bid_ref=lambda: None,
        )
        coordinator._mesh_scene_dirty = False
        coordinator._placement = SimpleNamespace()
        coordinator._do_file_refresh = lambda: calls.append("refresh")
        coordinator._finish_refresh = lambda: calls.append("finish")
        coordinator._on_database_refreshed(
            file_path="background.mdb",
            external_change=True,
        )
        self.assertEqual(
            calls,
            [("cancel", "background.mdb"), "start", "refresh", "finish"],
        )

    def test_database_refresh_stops_when_deferred_flush_fails(self):
        calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator._deferred_persistence = SimpleNamespace(
            flush_for_file=lambda file_path: calls.append(("flush", file_path)) or False
        )
        coordinator._nav = SimpleNamespace(
            start_refresh=lambda _ui_state, _placement, selected_area_uid="": calls.append(
                "start"
            )
            or True
        )
        coordinator._do_file_refresh = lambda: calls.append("refresh")
        coordinator._finish_refresh = lambda: calls.append("finish")
        coordinator._on_database_refreshed(file_path="a.mdb")
        self.assertEqual(calls, [("flush", "a.mdb")])

    def test_page_area_change_updates_model_immediately_and_defers_write(self):
        area_selections = {"p1": None}
        direct_writes = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator._page_settings_bar = None
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        selected_page_reads = []

        def selected_page_uids():
            selected_page_reads.append(area_selections["p1"])
            return ["p1"]

        page_owner = object()
        coordinator.project_data = SimpleNamespace(
            get_page_area_selections=lambda: area_selections,
            get_selected_page_uids=selected_page_uids,
            get_page=lambda page_uid: page_owner if page_uid == "p1" else None,
        )
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="p1",
            get_selected_bid_ref=lambda: BidRef("a.mdb", "bid-1"),
        )
        coordinator._deferred_persistence = RecordingDeferredPersistence()
        coordinator._project_write_service = SimpleNamespace(
            save_page_area=lambda db_path, page_uid, area_uid, publish_database_refreshed_after_write=True: direct_writes.append(
                (
                    db_path,
                    page_uid,
                    area_uid,
                    publish_database_refreshed_after_write,
                )
            )
        )
        plan_updates = []
        self._install_hidden_2d_mesh_state(coordinator)
        coordinator._viewer = SimpleNamespace(
            update_page_area_selection=lambda _page_uid: False,
            update_plan_view=lambda page_uid: plan_updates.append(page_uid),
            update_viewers=lambda _page_uids: None,
        )
        detached_updates = []
        coordinator.main_window = SimpleNamespace(
            refresh_detached_plan_area_selection=lambda page_uid: detached_updates.append(
                page_uid
            )
        )
        hotlink_updates = []
        coordinator._apply_pending_hotlink_named_view_focus = (
            lambda require_stable: hotlink_updates.append(require_stable)
        )
        coordinator._refresh_takeoff_dependent_page_controls = (
            lambda page_uid: self.fail(f"unexpected inactive page refresh {page_uid}")
        )
        coordinator._on_page_area_changed("a.mdb", "p1", "2")
        self.assertEqual(coordinator.ui_state_manager.selected_area_uid, "2")
        self.assertEqual(area_selections["p1"], "2")
        self.assertEqual(
            coordinator._deferred_persistence.page_area_calls,
            [("a.mdb", "p1", "2")],
        )
        self.assertEqual(plan_updates, ["p1"])
        self.assertEqual(detached_updates, ["p1"])
        self.assertEqual(coordinator.mesh_refresh_calls, [])
        self.assertTrue(coordinator._mesh_scene_dirty)
        self.assertEqual(coordinator._dirty_mesh_page_uids, {"p1"})
        self.assertEqual(selected_page_reads, ["2"])
        self.assertEqual(hotlink_updates, [True])
        self.assertEqual(direct_writes, [])

    def test_page_area_clear_updates_model_to_no_filter(self):
        area_selections = {"p1": "2"}
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator._page_settings_bar = None
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        page_owner = object()
        coordinator.project_data = SimpleNamespace(
            get_page_area_selections=lambda: area_selections,
            get_selected_page_uids=lambda: ["p1"],
            get_page=lambda page_uid: page_owner if page_uid == "p1" else None,
        )
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="p1",
            get_selected_bid_ref=lambda: BidRef("a.mdb", "bid-1"),
        )
        coordinator._deferred_persistence = RecordingDeferredPersistence()
        self._install_hidden_2d_mesh_state(coordinator)
        coordinator._viewer = SimpleNamespace(
            update_page_area_selection=lambda _page_uid: False,
            update_plan_view=lambda _page_uid: None,
            update_viewers=lambda _page_uids: None,
        )
        coordinator.main_window = SimpleNamespace(
            refresh_detached_plan_area_selection=lambda _page_uid: None
        )
        coordinator._apply_pending_hotlink_named_view_focus = (
            lambda require_stable: None
        )
        coordinator._refresh_takeoff_dependent_page_controls = lambda _page_uid: None
        coordinator._on_page_area_changed("a.mdb", "p1", "")
        self.assertEqual(coordinator.ui_state_manager.selected_area_uid, "")
        self.assertIsNone(area_selections["p1"])
        self.assertEqual(
            coordinator._deferred_persistence.page_area_calls,
            [("a.mdb", "p1", "")],
        )
        self.assertEqual(coordinator.mesh_refresh_calls, [])
        self.assertTrue(coordinator._mesh_scene_dirty)
        self.assertEqual(coordinator._dirty_mesh_page_uids, {"p1"})

    def test_page_area_failure_restores_only_originating_page(self):
        area_selections = {"p1": "area-1", "p2": "area-2"}
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator._page_settings_bar = None
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        coordinator.project_data = SimpleNamespace(
            get_page_area_selections=lambda: area_selections,
            get_selected_page_uids=lambda: ["p1"],
            get_page=lambda page_uid: object() if page_uid in area_selections else None,
        )
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="p1",
            selected_area_uid="area-1",
            get_selected_bid_ref=lambda: BidRef("a.mdb", "bid-1"),
        )
        coordinator._deferred_persistence = RecordingDeferredPersistence()
        coordinator._viewer = SimpleNamespace(
            update_page_area_selection=lambda _page_uid: False,
            update_plan_view=lambda _page_uid: None,
        )
        coordinator.main_window = SimpleNamespace(
            refresh_detached_plan_area_selection=lambda _page_uid: None
        )
        coordinator._request_or_defer_mesh_refresh = lambda _page_uids: None
        coordinator._apply_pending_hotlink_named_view_focus = (
            lambda require_stable: None
        )
        coordinator._on_page_area_changed("a.mdb", "p1", "area-3")
        callbacks = coordinator._deferred_persistence.page_area_callbacks[0]
        callbacks["restore_authoritative"]()
        self.assertEqual(area_selections["p1"], "area-1")
        coordinator.ui_state_manager.active_page_uid = "p2"
        callbacks["project_value"]()
        self.assertEqual(area_selections["p1"], "area-1")


class CurrentPageContentReadFailureTests(unittest.TestCase):
    def test_current_page_delete_stops_when_content_verification_is_unavailable(self):
        critical = Mock()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.can_delete_current_page = lambda: True
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-1",
            get_selected_bid_ref=lambda: BidRef("project.mdb", "bid-1"),
        )
        coordinator.project_data = SimpleNamespace(
            get_page=lambda _uid: object(),
        )
        coordinator._project_read_service = SimpleNamespace(
            get_pages_with_delete_content=lambda _file_path, _bid_uid: None
        )
        coordinator._stage_selection_after_page_delete = Mock()
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: False,
            delete_pages=Mock(side_effect=AssertionError("delete must not run")),
        )
        coordinator.main_window = object()
        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator."
            "show_critical",
            critical,
        ):
            coordinator.delete_current_page()
        critical.assert_called_once()
        coordinator._stage_selection_after_page_delete.assert_not_called()
        coordinator._project_write_service.delete_pages.assert_not_called()


class UiEventCoordinatorPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_annotation_tool_actions_do_not_use_backout_toggle_handler(self):
        _preferences_support__app()

        class FakeToolbar:
            def __init__(self):
                self.backout_action = None
                self.annotation_tool_actions = None
                self.refresh_calls = 0
                self.backout_refresh_calls = 0

            def set_backout_action(self, action):
                self.backout_action = action

            def set_annotation_tool_actions(self, actions):
                self.annotation_tool_actions = actions

            def refresh(self):
                self.refresh_calls += 1

            def refresh_backout_action(self):
                self.backout_refresh_calls += 1

        toolbar = FakeToolbar()
        calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._toolbar = toolbar
        coordinator._on_backout_toggled = lambda checked: calls.append(checked)
        dimension_action = QtGui.QAction()
        dimension_action.setCheckable(True)
        UIEventCoordinator.set_annotation_tool_actions(coordinator, [dimension_action])
        dimension_action.setChecked(True)
        self.assertEqual(calls, [])
        self.assertEqual(toolbar.annotation_tool_actions, [dimension_action])
        self.assertEqual(toolbar.refresh_calls, 1)
        self.assertEqual(toolbar.backout_refresh_calls, 0)
        backout_action = QtGui.QAction()
        backout_action.setCheckable(True)
        UIEventCoordinator.set_backout_action(coordinator, backout_action)
        backout_action.setChecked(True)
        self.assertEqual(calls, [True])
        self.assertIs(toolbar.backout_action, backout_action)
        self.assertEqual(toolbar.backout_refresh_calls, 1)

    def test_ui_event_coordinator_delegates_app_config_application(self):
        class FakeAppConfigPresentation:
            def __init__(self):
                self.calls = []

            def apply_updated_options(self, window, config_model, changed_values):
                self.calls.append((window, config_model, changed_values))
                return False

        class FakeMenuController:
            def __init__(self):
                self.updated = False

            def update_menu_states(self):
                self.updated = True

        fake_config = SimpleNamespace(show_toolbar_text=True)
        menu_controller = FakeMenuController()
        main_window = SimpleNamespace(
            _config_model=fake_config,
            menu_controller=menu_controller,
        )
        sync_calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = main_window
        coordinator.ui_state_manager = SimpleNamespace(
            sync_from_config=lambda: sync_calls.append("sync"),
            highlighted_condition_uids=[],
        )
        coordinator._app_config_presentation = FakeAppConfigPresentation()
        coordinator._on_app_config_updated(value={"show_toolbar_text": True})
        self.assertEqual(sync_calls, ["sync"])
        self.assertTrue(menu_controller.updated)
        self.assertEqual(
            coordinator._app_config_presentation.calls,
            [(main_window, fake_config, {"show_toolbar_text": True})],
        )

    def test_ui_event_coordinator_keeps_condition_display_refresh_orchestration(self):
        class FakeAppConfigPresentation:
            def apply_updated_options(self, window, config_model, changed_values):
                return True

        class FakeUiAccess:
            def is_allowed(self, feature):
                return True

        calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = SimpleNamespace(
            _config_model=SimpleNamespace(),
            menu_controller=SimpleNamespace(
                update_menu_states=lambda: calls.append("menu")
            ),
            refresh_detached_plan_views=lambda: calls.append("detached"),
        )
        coordinator.ui_state_manager = SimpleNamespace(
            sync_from_config=lambda: calls.append("sync"),
            highlighted_condition_uids=["cond-1"],
            get_selected_bid_ref=lambda: object(),
        )
        coordinator._app_config_presentation = FakeAppConfigPresentation()
        coordinator._sidebar = SimpleNamespace(
            refresh_conditions_from_memory=lambda: calls.extend(
                ("conditions", "summary")
            ),
        )
        coordinator.conditions_sidebar = SimpleNamespace(
            highlight_conditions=lambda uids: calls.append(("highlight", list(uids)))
        )
        coordinator.ui_access_manager = FakeUiAccess()
        coordinator.project_data = SimpleNamespace(
            get_selected_page_uids=lambda: ["page-1"]
        )
        coordinator._tab_widget = SimpleNamespace(
            currentIndex=lambda: TAB_INDEX_TAKEOFF
        )
        coordinator._view_stack = SimpleNamespace(currentIndex=lambda: 0)
        coordinator._mesh_window = None
        coordinator.opengl_viewer = None
        coordinator._mesh_scene_dirty = False
        coordinator._dirty_mesh_page_uids = set()
        coordinator._pending_dirty_mesh_refresh = False
        coordinator._last_mesh_scene = None
        coordinator.visualization_service = SimpleNamespace(
            refresh_mesh_view=lambda page_uids: calls.append(("viewers", page_uids))
        )
        coordinator._viewer = SimpleNamespace()
        coordinator._update_plan_view_for_active = lambda: calls.append("plan_view")
        coordinator._on_app_config_updated(
            value={"display_mode_3d": Config.DISPLAY_MODE_ORIGINAL}
        )
        self.assertEqual(
            calls,
            [
                "sync",
                "menu",
                "conditions",
                "summary",
                ("highlight", ["cond-1"]),
                ("viewers", ["page-1"]),
                "plan_view",
                "detached",
            ],
        )

    def test_condition_display_refresh_does_not_request_unlicensed_3d_scene(self):
        calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = SimpleNamespace(
            refresh_detached_plan_views=lambda: calls.append("detached")
        )
        coordinator.ui_state_manager = SimpleNamespace(highlighted_condition_uids=[])
        coordinator._sidebar = SimpleNamespace(
            refresh_conditions_from_memory=lambda: calls.extend(
                ("conditions", "summary")
            )
        )
        coordinator.conditions_sidebar = None
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda feature: feature == Feature.VIEW_2D
        )
        coordinator.project_data = SimpleNamespace(
            get_selected_page_uids=lambda: ["page-1"]
        )
        coordinator._request_or_defer_mesh_refresh = lambda _pages: self.fail(
            "unlicensed 3D refresh must not be requested"
        )
        coordinator._update_plan_view_for_active = lambda: calls.append("plan")
        coordinator._refresh_condition_display_after_app_config_change()
        self.assertEqual(calls, ["conditions", "summary", "plan", "detached"])


class PageSettingsModalCoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_access_page_setting_modals_tolerate_parent_destruction(self):
        class DestroyedWithParentDialog(QtWidgets.QDialog):
            def __init__(self, *args, **_kwargs):
                super().__init__(args[1])

            def cleanup(self):
                pass

        cases = (
            ("AdjustImagesDialog", "open_adjust_images_dialog"),
            ("SetScaleDialog", "open_set_scale_dialog"),
            ("RenamePageDialog", "open_rename_page_dialog"),
        )
        for dialog_name, method_name in cases:
            with self.subTest(dialog=dialog_name):
                window = QtWidgets.QWidget()
                page = Page(uid="page-1", name="Page 1")
                bid_ref = BidRef("database.mdb", "8")
                coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
                coordinator.main_window = window
                coordinator.event_bus = EventBus()
                coordinator._icon_provider = None
                coordinator.ui_state_manager = SimpleNamespace(
                    active_page_uid=page.uid,
                    get_selected_bid_ref=lambda: bid_ref,
                )
                coordinator.ui_access_manager = SimpleNamespace(
                    is_allowed=lambda _feature: True
                )
                coordinator.project_data = SimpleNamespace(
                    get_page=lambda uid: page if uid == page.uid else None
                )
                coordinator.takeoff_sidebar = SimpleNamespace(
                    get_page_order=lambda: [page.uid]
                )
                coordinator._project_write_service = SimpleNamespace(
                    uses_sql_collaboration_mutations=lambda _database_id: False
                )

                def destroy_parent(_dialog, _event_bus):
                    delete(window)
                    return QtWidgets.QDialog.DialogCode.Rejected

                with (
                    patch(
                        "ost_visualizer.presentation.coordinators."
                        f"ui_event_coordinator.{dialog_name}",
                        DestroyedWithParentDialog,
                    ),
                    patch(
                        "ost_visualizer.presentation.coordinators.ui_event_coordinator."
                        "exec_with_ost_blocking",
                        side_effect=destroy_parent,
                    ),
                ):
                    getattr(coordinator, method_name)()

    def test_mdb_set_scale_rejects_dialog_save_after_bid_context_changes(self):
        save_calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-1",
            get_selected_bid_ref=lambda: BidRef("other.mdb", "bid-2"),
        )
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        coordinator.takeoff_sidebar = SimpleNamespace(get_page_order=lambda: ["page-1"])
        coordinator.project_data = SimpleNamespace(get_page=lambda _uid: object())
        coordinator._deferred_persistence = SimpleNamespace(
            flush_for_file=lambda _file_path: True
        )
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: False,
            save_page_scale=lambda *args: save_calls.append(args) or True,
            save_page_scales=lambda *args: save_calls.append(args) or True,
        )
        saved = coordinator._save_scale_settings(
            BidRef("database.mdb", "bid-1"),
            "page-1",
            object(),
            ScaleSettings(1.0, 48.0, False),
        )
        self.assertFalse(saved)
        self.assertEqual(save_calls, [])


class DialogLifecycleTests(unittest.TestCase):
    def test_collaboration_modal_return_marks_destroyed_dialog_unexecuted(self):
        _dialog_lifecycle_support__app()
        parent = QtWidgets.QWidget()
        dialog = QtWidgets.QDialog(parent)
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.event_bus = EventBus()
        hierarchy_entry = HierarchyFileEntry(file_path="database")
        coordinator.project_data = SimpleNamespace(
            get_hierarchy=lambda: HierarchyData(loaded_files=[hierarchy_entry])
        )
        handle = EditLeaseHandle(
            database_id="database",
            draft_id="draft",
            runtime_generation=1,
            operation_id="dialog",
            owning_surface="main-window-dialog",
            resources=(ResourceRef("page", "page-1", 8),),
        )
        released = []
        cleaned = []
        after_close = []
        coordinator.end_collaboration_edit = released.append

        def request_edit(_database_id, _resources, callback, **_kwargs):
            callback(EditLeaseResult(True, handle=handle))

        coordinator.request_collaboration_edit = request_edit

        def destroy_parent(_dialog, _event_bus):
            delete(parent)
            return QtWidgets.QDialog.DialogCode.Rejected

        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator."
            "exec_with_ost_blocking",
            side_effect=destroy_parent,
        ):
            coordinator._exec_with_collaboration_lease(
                dialog,
                "database",
                handle.resources,
                lambda: cleaned.append(True),
                after_close.append,
            )
        self.assertEqual(released, [handle])
        self.assertEqual(cleaned, [True])
        self.assertEqual(after_close, [False])

    def test_collaboration_modal_rejects_same_path_database_replacement(self):
        _dialog_lifecycle_support__app()
        database_id = "database"
        original_entry = HierarchyFileEntry(file_path=database_id)
        hierarchy = [HierarchyData(loaded_files=[original_entry])]
        dialog = QtWidgets.QDialog()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.event_bus = EventBus()
        coordinator.project_data = SimpleNamespace(get_hierarchy=lambda: hierarchy[0])
        callbacks = []
        released = []
        cleaned = []
        executions = []
        handle = EditLeaseHandle(
            database_id=database_id,
            draft_id="draft",
            runtime_generation=1,
            operation_id="dialog",
            owning_surface="main-window-dialog",
            resources=(ResourceRef("condition_type", "1"),),
        )
        coordinator.request_collaboration_edit = (
            lambda _database_id, _resources, callback, **_kwargs: callbacks.append(
                callback
            )
        )
        coordinator.end_collaboration_edit = released.append
        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator."
            "exec_with_ost_blocking",
            lambda *_args: executions.append(True),
        ):
            coordinator._exec_with_collaboration_lease(
                dialog,
                database_id,
                handle.resources,
                lambda: cleaned.append(True),
            )
            hierarchy[0] = HierarchyData(
                loaded_files=[HierarchyFileEntry(file_path=database_id)]
            )
            callbacks[0](EditLeaseResult(True, handle=handle))
        self.assertEqual(executions, [])
        self.assertEqual(released, [handle])
        self.assertEqual(cleaned, [True])

    def test_collaboration_modal_consumes_duplicate_lease_callback_once(self):
        _dialog_lifecycle_support__app()
        dialog = QtWidgets.QDialog()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.event_bus = EventBus()
        hierarchy_entry = HierarchyFileEntry(file_path="database")
        coordinator.project_data = SimpleNamespace(
            get_hierarchy=lambda: HierarchyData(loaded_files=[hierarchy_entry])
        )
        callbacks = []
        released = []
        cleaned = []
        executions = []
        handle = EditLeaseHandle(
            database_id="database",
            draft_id="draft",
            runtime_generation=1,
            operation_id="dialog",
            owning_surface="main-window-dialog",
            resources=(ResourceRef("condition_type", "1"),),
        )
        coordinator.request_collaboration_edit = (
            lambda _database_id, _resources, callback, **_kwargs: callbacks.append(
                callback
            )
        )
        coordinator.end_collaboration_edit = released.append
        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator."
            "exec_with_ost_blocking",
            lambda *_args: executions.append(True),
        ):
            coordinator._exec_with_collaboration_lease(
                dialog,
                "database",
                handle.resources,
                lambda: cleaned.append(True),
            )
            result = EditLeaseResult(True, handle=handle)
            callbacks[0](result)
            callbacks[0](result)
        self.assertEqual(executions, [True])
        self.assertEqual(released, [handle])
        self.assertEqual(cleaned, [True])

    def test_collaboration_modal_does_not_execute_destroyed_dialog(self):
        _dialog_lifecycle_support__app()
        dialog = QtWidgets.QDialog()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.event_bus = EventBus()
        hierarchy_entry = HierarchyFileEntry(file_path="database")
        coordinator.project_data = SimpleNamespace(
            get_hierarchy=lambda: HierarchyData(loaded_files=[hierarchy_entry])
        )
        callbacks = []
        released = []
        cleaned = []
        executions = []
        handle = EditLeaseHandle(
            database_id="database",
            draft_id="draft",
            runtime_generation=1,
            operation_id="dialog",
            owning_surface="main-window-dialog",
            resources=(ResourceRef("condition_type", "1"),),
        )
        coordinator.request_collaboration_edit = (
            lambda _database_id, _resources, callback, **_kwargs: callbacks.append(
                callback
            )
        )
        coordinator.end_collaboration_edit = released.append
        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator."
            "exec_with_ost_blocking",
            lambda *_args: executions.append(True),
        ):
            coordinator._exec_with_collaboration_lease(
                dialog,
                "database",
                handle.resources,
                lambda: cleaned.append(True),
            )
            delete(dialog)
            callbacks[0](EditLeaseResult(True, handle=handle))
        self.assertEqual(executions, [])
        self.assertEqual(released, [handle])
        self.assertEqual(cleaned, [True])

    def test_ui_event_cleanup_attempts_later_stages_and_retries_unsubscribe(self):
        calls = []

        class EventBus:
            def __init__(self):
                self.attempts = 0

            def unsubscribe(self, event_type, _callback):
                calls.append(f"unsubscribe:{event_type.__name__}")
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("transient unsubscribe")

        def failing(name):
            def cleanup():
                calls.append(name)
                raise RuntimeError(f"{name} failed")

            return cleanup

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.project_operations = SimpleNamespace(
            cancel_navigation_load=failing("navigation")
        )
        coordinator._status_panel = None
        coordinator._sync_collaboration_status = lambda *_args, **_kwargs: None
        coordinator._invalidate_mesh_scene_request = lambda: None
        coordinator._plan_view_handler = None
        coordinator._view_stack = None
        coordinator._tab_widget = None
        coordinator._undo_service = None
        coordinator.event_bus = EventBus()
        coordinator._subscriptions = [
            (AppEvents.LICENSE_STATUS_CHANGED, lambda **_: None),
            (AppEvents.FILE_OPENED, lambda **_: None),
        ]
        coordinator._plan_view_signaler = None
        coordinator._menu_state_signaler = None
        coordinator._bid_data_cache = None
        coordinator._pending_3d_takeoff_uids_by_bid = {}
        coordinator._mesh_window = None
        coordinator._mesh_window_action = None
        coordinator._placement = SimpleNamespace(cleanup=failing("placement"))
        coordinator.opengl_viewer = SimpleNamespace(
            cleanup=lambda: calls.append("viewer")
        )
        coordinator.takeoff_sidebar = None
        coordinator.plan_view = None
        coordinator._sidebar = None
        coordinator._viewer = None
        coordinator._toolbar = None
        coordinator.main_window = object()
        coordinator.ui_state_manager = object()
        coordinator.ui_access_manager = object()
        coordinator.project_data = object()
        coordinator.visualization_service = object()
        coordinator._color_service = object()
        coordinator._icon_provider = object()
        coordinator._project_write_service = object()
        coordinator._project_read_service = object()
        coordinator.conditions_sidebar = None
        coordinator.condition_summary_tab = None
        coordinator._condition_handler = object()
        coordinator._deferred_persistence = object()
        with self.assertRaises(ExceptionGroup) as captured:
            coordinator.cleanup()
        self.assertEqual(
            [str(error) for error in captured.exception.exceptions],
            [
                "navigation failed",
                "transient unsubscribe",
                "placement failed",
            ],
        )
        self.assertIn("viewer", calls)
        self.assertEqual(len(coordinator._subscriptions), 1)
        coordinator.cleanup()
        self.assertEqual(coordinator._subscriptions, [])
        self.assertIsNone(coordinator.event_bus)


class BidLockPermissionTests(unittest.TestCase):
    def test_capability_change_refreshes_access_before_projecting_controls(self):
        calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(selected_file_path="sql-db-1")
        coordinator.ui_access_manager = SimpleNamespace(
            refresh=lambda: calls.append("refresh"),
            is_allowed=lambda feature: feature == Feature.SELECT_PLAN_ITEMS,
            is_database_editable=lambda: False,
        )
        coordinator._deferred_persistence = SimpleNamespace(
            cancel_for_file=lambda file_path: calls.append(("cancel", file_path))
        )
        coordinator.main_window = SimpleNamespace(
            menu_controller=SimpleNamespace(
                update_menu_states=lambda: calls.append("menu")
            )
        )
        coordinator._toolbar = SimpleNamespace(refresh=lambda: calls.append("toolbar"))
        coordinator._mesh_window = SimpleNamespace(
            set_pick_enabled=lambda enabled: calls.append(("mesh-pick", enabled)),
            set_editing_enabled=lambda enabled: calls.append(("mesh-edit", enabled)),
        )
        coordinator._on_database_capabilities_changed("other-db")
        self.assertEqual(calls, [])
        coordinator._on_database_capabilities_changed("sql-db-1")
        self.assertEqual(
            calls,
            [
                "refresh",
                ("cancel", "sql-db-1"),
                "menu",
                ("mesh-pick", True),
                ("mesh-edit", False),
            ],
        )

    def test_writable_capability_refresh_does_not_discard_deferred_state(self):
        calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(selected_file_path="sql-db-1")
        coordinator.ui_access_manager = SimpleNamespace(
            refresh=lambda: calls.append("refresh"),
            is_database_editable=lambda: True,
        )
        coordinator._deferred_persistence = SimpleNamespace(
            cancel_for_file=lambda file_path: calls.append(("cancel", file_path))
        )
        coordinator._mesh_window = None
        coordinator._update_menu_state = lambda: calls.append("project")
        coordinator._on_database_capabilities_changed("sql-db-1")
        self.assertEqual(calls, ["refresh", "project"])


class MdbSqlBehaviorParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    @staticmethod
    def _result(status: MutationOutcomeStatus) -> QueuedMutationResult:
        return QueuedMutationResult(
            database_id="database",
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=status,
            commit_attempted=status == MutationOutcomeStatus.COMMITTED,
        )

    def test_sql_bid_lock_state_uses_hydrated_navigation_snapshot(self):
        locked_values = []
        coordinator = SimpleNamespace(
            project_data=SimpleNamespace(
                get_bid=lambda _bid_ref: SimpleNamespace(
                    status="Duplicate", status_uid="status-locked"
                ),
                get_job_status_snapshot=lambda _database_id: [
                    JobStatus(uid="status-unlocked", name="Duplicate", locked=False),
                    JobStatus(uid="status-locked", name="Duplicate", locked=True),
                ],
                set_current_bid_locked=locked_values.append,
            ),
            _project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _database_id: True
            ),
            _project_read_service=SimpleNamespace(
                is_bid_locked=lambda *_args: self.fail(
                    "SQL bid activation must not query the database on the Qt thread"
                )
            ),
        )
        UIEventCoordinator._resolve_bid_lock_state(
            coordinator, BidRef("sql-database", "bid-1")
        )
        self.assertEqual(locked_values, [True])

    def test_mdb_bid_lock_state_keeps_local_reader_strategy(self):
        locked_values = []
        read_calls = []
        coordinator = SimpleNamespace(
            project_data=SimpleNamespace(
                get_bid=lambda _bid_ref: SimpleNamespace(
                    status="Duplicate", status_uid="status-locked"
                ),
                get_job_status_snapshot=lambda _database_id: self.fail(
                    "MDB lock state must retain its local reader strategy"
                ),
                set_current_bid_locked=locked_values.append,
            ),
            _project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _database_id: False
            ),
            _project_read_service=SimpleNamespace(
                is_bid_locked=lambda database_id, status: (
                    read_calls.append((database_id, status)) or True
                )
            ),
        )
        UIEventCoordinator._resolve_bid_lock_state(
            coordinator, BidRef("local.mdb", "bid-1")
        )
        self.assertEqual(read_calls, [("local.mdb", "status-locked")])
        self.assertEqual(locked_values, [True])

    def test_main_sql_scale_failure_restores_only_its_current_page(self):
        callbacks = []
        refreshes = []

        def queue_page_setting(*_args, **kwargs):
            callbacks.append(kwargs["callback"])
            return True

        state = SimpleNamespace(
            active_page_uid="page-1",
            get_selected_bid_ref=lambda: BidRef("sql-database", "bid-1"),
        )
        coordinator = SimpleNamespace(
            _flush_deferred_for_file=lambda _database_id: True,
            _project_write_service=SimpleNamespace(
                queue_page_setting_if_sql=queue_page_setting,
                save_page_scale=lambda *_args: self.fail(
                    "SQL scale changes must not use the synchronous write path"
                ),
            ),
            ui_state_manager=state,
            _update_page_settings_bar=refreshes.append,
        )
        UIEventCoordinator._on_page_scale_changed(
            coordinator, "sql-database", "page-1", 0.25, 12.0
        )
        callbacks[0](self._result(MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED))
        self.assertEqual(refreshes, [])
        state.active_page_uid = "page-2"
        callbacks[0](self._result(MutationOutcomeStatus.CONFLICT))
        self.assertEqual(refreshes, [])
        state.active_page_uid = "page-1"
        callbacks[0](self._result(MutationOutcomeStatus.CONFLICT))
        self.assertEqual(refreshes, ["page-1"])


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
        coordinator._viewer = _detached_support_FakeHotlinkViewer(plan_view)
        coordinator._sidebar = _detached_support_FakeHotlinkSidebar()
        coordinator._tab_widget = _detached_support_FakeHotlinkTabWidget()
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
        coordinator._update_export_menu_state = lambda: None
        coordinator._toolbar = SimpleNamespace(refresh=lambda: None)
        return coordinator

    def test_annotation_change_for_detached_page_does_not_move_main_plan_view(self):
        plan_view = _detached_support_FakeHotlinkPlanView()
        plan_view.current_page_uid = "page-43"
        coordinator = self._make_main_hotlink_coordinator(plan_view)
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-43",
            get_selected_bid_ref=lambda: None,
        )
        coordinator._on_annotations_changed(
            page_uid="page-21",
            annotation_uids=["ann-21"],
            annotation_types=["text"],
        )
        self.assertEqual(coordinator._viewer.updated_pages, [])
        self.assertEqual(plan_view.current_page_uid, "page-43")

    def test_annotation_change_for_active_page_refreshes_main_plan_view(self):
        plan_view = _detached_support_FakeHotlinkPlanView()
        plan_view.current_page_uid = "page-43"
        coordinator = self._make_main_hotlink_coordinator(plan_view)
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-43",
            get_selected_bid_ref=lambda: None,
        )
        coordinator._on_annotations_changed(
            page_uid="page-43",
            annotation_uids=["ann-43"],
            annotation_types=["text"],
        )
        self.assertEqual(coordinator._viewer.updated_pages, ["page-43"])
        self.assertEqual(
            coordinator._viewer.annotation_updates,
            [("page-43", ["ann-43"], ["text"])],
        )

    def test_main_hotlink_focus_uses_named_view_rectangle_after_page_update(self):
        plan_view = _detached_support_FakeHotlinkPlanView()
        coordinator = self._make_main_hotlink_coordinator(plan_view)
        coordinator.navigate_to_takeoff_page("page-2", "view-1")
        self.assertEqual(coordinator._viewer.updated_pages, ["page-2"])
        self.assertEqual(plan_view.deferred_states, [True])
        self.assertEqual(plan_view.zoom_rects, [(1.0, 2.0, 11.0, 12.0, 0.1)])
        self.assertEqual(plan_view.reveals, 1)

    def test_main_hotlink_focus_on_loaded_page_does_not_defer_visuals(self):
        plan_view = _detached_support_FakeHotlinkPlanView()
        plan_view.current_page_uid = "page-2"
        coordinator = self._make_main_hotlink_coordinator(plan_view)
        coordinator.navigate_to_takeoff_page("page-2", "view-1")
        self.assertEqual(plan_view.deferred_states, [])
        self.assertEqual(plan_view.zoom_rects, [(1.0, 2.0, 11.0, 12.0, 0.1)])

    def test_main_hotlink_focus_waits_until_plan_view_is_visible(self):
        plan_view = _detached_support_FakeHotlinkPlanView(visible=False)
        coordinator = self._make_main_hotlink_coordinator(plan_view)
        coordinator.navigate_to_takeoff_page("page-2", "view-1")
        self.assertEqual(plan_view.zoom_rects, [])
        self.assertEqual(plan_view.reveals, 0)
        plan_view._visible = True
        coordinator._on_plan_view_page_fully_loaded()
        self.assertEqual(plan_view.zoom_rects, [(1.0, 2.0, 11.0, 12.0, 0.1)])
        self.assertEqual(plan_view.reveals, 1)

    def test_main_hotlink_pending_focus_clears_when_another_page_loads(self):
        plan_view = _detached_support_FakeHotlinkPlanView(visible=False)
        coordinator = self._make_main_hotlink_coordinator(plan_view)
        coordinator.navigate_to_takeoff_page("page-2", "view-1")
        plan_view._visible = True
        plan_view.current_page_uid = "page-3"
        coordinator._on_plan_view_page_fully_loaded()
        plan_view.current_page_uid = "page-2"
        coordinator._on_plan_view_page_fully_loaded()
        self.assertEqual(plan_view.zoom_rects, [])
        self.assertEqual(plan_view.reveals, 1)

    def test_bid_workspace_reset_invalidates_pending_hotlink_focus(self):
        plan_view = _detached_support_FakeHotlinkPlanView(visible=False)
        coordinator = self._make_main_hotlink_coordinator(plan_view)
        coordinator._takeoff_workspace_bid_ref = BidRef("old.mdb", "bid-old")
        coordinator.navigate_to_takeoff_page("page-2", "view-1")
        coordinator._reset_takeoff_workspace_state(clear_sidebars=False)
        plan_view._visible = True
        coordinator._on_plan_view_page_fully_loaded()
        self.assertEqual(plan_view.zoom_rects, [])
        self.assertEqual(plan_view.reveals, 1)


class PageScaleProjectionTests(unittest.TestCase):
    def test_scale_event_refreshes_only_affected_surfaces(self):
        calls = []
        bid_ref = BidRef("scale.mdb", "7")
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="42",
            get_selected_bid_ref=lambda: bid_ref,
        )
        coordinator.project_data = SimpleNamespace(
            get_selected_page_uids=lambda: ["42", "43"]
        )
        coordinator._update_page_settings_bar = lambda uid: calls.append(("bar", uid))
        coordinator._viewer = SimpleNamespace(
            update_plan_view=lambda uid, **kwargs: calls.append(("plan", uid, kwargs))
        )
        coordinator._apply_pending_hotlink_named_view_focus = (
            lambda require_stable: calls.append(("hotlink", require_stable))
        )
        coordinator._request_or_defer_mesh_refresh = lambda uids: calls.append(
            ("mesh", tuple(uids))
        )
        coordinator._sidebar = Mock()
        coordinator._is_summary_tab_active = lambda: False
        coordinator._on_page_metadata_changed("scale.mdb", "7", ("42",), ("scale",))
        self.assertEqual(calls[0], ("bar", "42"))
        self.assertEqual(calls[1], ("plan", "42", {"force_overlay_refresh": True}))
        self.assertIn(("mesh", ("42", "43")), calls)


class PageScaleSurfaceSyncRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_scale_refresh_skips_project_tree_rebuild_and_preserves_tool_contract(
        self,
    ) -> None:
        calls = []
        bid_ref = BidRef("scale-sync.mdb", "7")
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._deferred_persistence = SimpleNamespace(
            cancel_for_file=lambda _path: None
        )
        coordinator._flush_deferred_for_file = lambda _path: True
        coordinator._nav = SimpleNamespace(start_refresh=lambda *_args, **_kwargs: True)
        coordinator._placement = SimpleNamespace()
        coordinator.ui_state_manager = SimpleNamespace(
            selected_area_uid="",
            selected_page_uids=["page-1"],
            get_selected_bid_ref=lambda: bid_ref,
        )
        coordinator.project_data = SimpleNamespace(
            get_selected_page_uids=lambda: ["page-1"]
        )
        coordinator._clear_mesh_views_for_scene_update = lambda: calls.append(
            "clear-mesh"
        )
        coordinator._mark_mesh_scene_dirty = lambda pages: calls.append(
            ("dirty-mesh", tuple(pages))
        )
        coordinator._do_file_refresh = (
            lambda *, rebuild_project_tree=True: calls.append(
                ("refresh", rebuild_project_tree)
            )
        )
        coordinator._finish_refresh = (
            lambda *, accept_reconstructed_placement_conditions=False: calls.append(
                ("finish", accept_reconstructed_placement_conditions)
            )
        )
        coordinator._flush_dirty_mesh_refresh_if_needed = lambda: calls.append(
            "flush-mesh"
        )
        coordinator._on_database_refreshed(
            file_path=bid_ref.file_path,
            image_sources_unchanged=True,
            page_scale_uids=("page-1",),
        )
        self.assertIn(("refresh", False), calls)
        self.assertIn(("finish", True), calls)
        self.assertIn(("dirty-mesh", ("page-1",)), calls)

    def test_scale_refresh_rebuilds_bid_cache_without_rebuilding_project_tree(
        self,
    ) -> None:
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        hierarchy = object()
        loaded_files = object()
        cached = []
        rebuilt = []
        coordinator.project_data = SimpleNamespace(get_hierarchy=lambda: hierarchy)
        coordinator._cache_bid_data = cached.append
        coordinator.main_window = SimpleNamespace(
            project_view=SimpleNamespace(
                build_complete_structure=rebuilt.append,
            )
        )
        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator.build_loaded_files",
            return_value=loaded_files,
        ):
            coordinator._do_file_refresh(rebuild_project_tree=False)
        self.assertEqual(cached, [loaded_files])
        self.assertEqual(rebuilt, [])


class RefreshScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scale_fixture.SetScaleRepeatedApplyTests.setUpClass()

    def setUp(self):
        self.fixture = scale_fixture.SetScaleRepeatedApplyTests()
        self.fixture.setUp()
        self.service = self.fixture.service
        self.service._save_page_name = SimpleNamespace(execute=lambda *_args: True)
        self.info = HierarchyPageInfo("42", "Page 42")
        self.fixture.model.set_hierarchy(
            HierarchyData(
                loaded_files=[
                    HierarchyFileEntry(
                        "test.mdb",
                        orphan_bids=[
                            HierarchyBidInfo("7", pages_without_folder=[self.info])
                        ],
                    )
                ]
            )
        )

    def test_other_database_refresh_does_not_reconcile_active_workspace(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("active.mdb", "7"),
            selected_area_uid="",
            selected_page_uids=["42"],
        )
        coordinator._flush_deferred_for_file = Mock(return_value=True)
        coordinator._nav = Mock()
        coordinator._placement = Mock()
        coordinator._do_file_refresh = Mock()
        coordinator._finish_refresh = Mock()
        coordinator._clear_mesh_views_for_scene_update = Mock()
        coordinator._mark_mesh_scene_dirty = Mock()
        coordinator._flush_dirty_mesh_refresh_if_needed = Mock()
        coordinator._restore_project_tree_bid_selection_if_needed = Mock()
        coordinator._update_export_menu_state = Mock()
        coordinator._on_database_refreshed("other.mdb")
        coordinator._do_file_refresh.assert_called_once_with()
        coordinator._nav.start_refresh.assert_not_called()
        coordinator._finish_refresh.assert_not_called()
        coordinator._clear_mesh_views_for_scene_update.assert_not_called()

    def test_name_event_updates_main_labels_without_canvas_or_mesh_projection(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: self.fixture.bid_ref
        )
        coordinator.project_data = self.fixture.data
        coordinator.takeoff_sidebar = Mock()
        coordinator._sync_page_info_status = Mock()
        coordinator._is_summary_tab_active = lambda: False
        coordinator._viewer = Mock()
        coordinator._request_or_defer_mesh_refresh = Mock()
        coordinator._on_page_metadata_changed("test.mdb", "7", ("42",), ("name",))
        coordinator.takeoff_sidebar.refresh_page_labels.assert_called_once_with(
            [self.fixture.original]
        )
        self.assertEqual(coordinator._viewer.mock_calls, [])
        coordinator._request_or_defer_mesh_refresh.assert_not_called()


class TargetedRefreshOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scope_fixture.RefreshScopeTests.setUpClass()

    def setUp(self):
        self.case = scope_fixture.RefreshScopeTests()
        self.case.setUp()

    def test_local_area_event_updates_summary_and_mesh_without_repeating_picker_projection(
        self,
    ):
        fixture = self.case.fixture
        main = UIEventCoordinator.__new__(UIEventCoordinator)
        main.ui_state_manager = fixture.coordinator.ui_state_manager
        main.project_data = fixture.data
        main._page_settings_bar = Mock()
        main._sidebar = Mock()
        main._undo_service = Mock()
        main._request_or_defer_mesh_refresh = Mock()
        main._is_summary_tab_active = lambda: True
        main._on_remote_areas_changed(
            "test.mdb", "7", local_completion=True, page_controls_projected=True
        )
        main._page_settings_bar.load_bid_areas.assert_not_called()
        main._sidebar.load_condition_summary_from_memory.assert_called_once_with()
        main._request_or_defer_mesh_refresh.assert_called_once()
        main._undo_service.clear.assert_not_called()


class UIEventCoordinatorChaosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _chaos_app()

    def test_ui_event_coordinator_chaos_default_seeds(self):
        steps = _env_int("PRESENTATION_CHAOS_STEPS", DEFAULT_CHAOS_STEPS)
        for seed in _configured_seeds()[:3]:
            with self.subTest(seed=seed, steps=steps):
                harness = UIEventCoordinatorChaosHarness(seed + 6500, self)
                harness.run_random_actions(steps)

    def test_known_sequence_dirty_2d_changes_flush_when_3d_opens(self):
        harness = UIEventCoordinatorChaosHarness(9651, self)
        harness.run_sequence(
            [
                "switch_to_2d_view",
                "takeoffs_changed_active_page",
                "switch_to_3d_view",
                "native_scene_updated",
            ]
        )
        self.assertFalse(harness.coordinator._mesh_scene_dirty)
        self.assertFalse(harness.coordinator._pending_dirty_mesh_refresh)
        self.assertEqual(harness.coordinator._dirty_mesh_page_uids, set())

    def test_known_sequence_no_selected_pages_publishes_empty_mesh_scene(self):
        harness = UIEventCoordinatorChaosHarness(9652, self)
        harness.run_sequence(
            [
                "clear_selected_pages",
                "takeoffs_changed_active_page",
            ]
        )
        visualization = harness.coordinator.visualization_service
        self.assertEqual(visualization.mesh_pages, [[]])
        self.assertEqual(visualization.cancelled_mesh_refreshes, 0)
