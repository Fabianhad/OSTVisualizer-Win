import unittest
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.application.dtos.collaboration_dtos import (
    CollaborationStatus,
    EditLeaseHandle,
    EditLeaseLoss,
    EditLeaseResult,
    MutationOutcomeStatus,
    ResourceRef,
    SynchronizationState,
)
from ost_visualizer.application.dtos.mesh_geometry_dto import (
    MeshGeometry,
    MeshSceneIdentity,
)
from ost_visualizer.application.dtos.remote_projection_dtos import (
    RemoteProjectionBarrier,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.dtos.collaboration_resource_catalog import (
    CollaborationResourceFamily,
)
from ost_visualizer.application.dtos.conflict_resolution_dtos import (
    ConflictResolutionAction,
)
from ost_visualizer.application.services.project_write_service import WriteReloadResult
from ost_visualizer.application.interfaces.i_database_catalog import (
    DatabaseCatalogError,
)
from ost_visualizer.domain.entities.annotation import ANNOTATION_TYPE_TEXT
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.config import (
    TAB_INDEX_PROJECTS,
    TAB_INDEX_SUMMARY,
    TAB_INDEX_TAKEOFF,
)
from ost_visualizer.presentation.coordinators.navigation_state_machine import (
    NavigationStateMachine,
    NavState,
)
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
    _MeshScenePublication,
)
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.managers.ui_state_manager import UIStateManager
from ost_visualizer.presentation.utils.qt_callback_bridge import QtVoidCallback


class FakeUiState:
    def __init__(self, bid_ref=BidRef("test.mdb", "bid-1")):
        self.active_page_uid = "page-1"
        self.place_condition_uid = None
        self._bid_ref = bid_ref

    def get_selected_bid_ref(self):
        return self._bid_ref

    def clear_place_condition(self):
        self.place_condition_uid = None


class FakeSqlCollaboration:
    def update_presence(self, *_args):
        return None

    def status(self, database_id):
        return CollaborationStatus(database_id, SynchronizationState.STOPPED)


class FakeProjectData:
    def __init__(self):
        self.selected_page_uids = ["page-1"]

    def has_takeoffs_for_pages(self, page_uids):
        return page_uids == ["page-1"]

    def get_area_uids_with_takeoff(self):
        return {"0", "area-1"}

    def get_area_uids_with_takeoff_for_page(self, page_uid):
        return {"area-1"} if page_uid == "page-1" else set()

    def get_selected_page_uids(self):
        return list(self.selected_page_uids)

    def get_bid_conditions(self):
        return {}

    def get_page(self, page_uid):
        return None


class FakeTakeoffSidebar:
    def __init__(self):
        self.calls = []

    def set_page_has_takeoffs(self, page_uid, has_takeoffs=True):
        self.calls.append((page_uid, has_takeoffs))


class FakePageSettingsBar:
    def __init__(self):
        self.calls = []

    def update_area_usage(
        self, bid_areas_with_takeoff=None, page_areas_with_takeoff=None
    ):
        self.calls.append((bid_areas_with_takeoff, page_areas_with_takeoff))


class FakeDeferredPersistence:
    def flush_for_file(self, _file_path):
        return True


class FakeViewer:
    def __init__(self):
        self.plan_pages = []
        self.changed_takeoff_uids = []
        self.changed_annotation_uids = []
        self.changed_annotation_types = []
        self.viewer_pages = []
        self.remote_requests = []

    def update_plan_view(
        self,
        page_uid,
        changed_takeoff_uids=None,
        changed_annotation_uids=None,
        changed_annotation_types=None,
    ):
        self.plan_pages.append(page_uid)
        self.changed_takeoff_uids.append(
            None if changed_takeoff_uids is None else list(changed_takeoff_uids)
        )
        self.changed_annotation_uids.append(
            None if changed_annotation_uids is None else list(changed_annotation_uids)
        )
        self.changed_annotation_types.append(
            None if changed_annotation_types is None else list(changed_annotation_types)
        )

    def update_plan_view_for_active(
        self,
        changed_takeoff_uids=None,
        changed_annotation_uids=None,
        changed_annotation_types=None,
    ):
        self.plan_pages.append("active")
        self.changed_takeoff_uids.append(
            None if changed_takeoff_uids is None else list(changed_takeoff_uids)
        )
        self.changed_annotation_uids.append(
            None if changed_annotation_uids is None else list(changed_annotation_uids)
        )
        self.changed_annotation_types.append(
            None if changed_annotation_types is None else list(changed_annotation_types)
        )

    def update_viewers(self, page_uids):
        self.viewer_pages.append(list(page_uids))

    def request_remote_plan_update(self, **request):
        self.remote_requests.append(request)
        request["completion"](True)
        return True


class FakeMeshReceiver:
    def __init__(self, visible=True):
        self.mesh_calls = []
        self.clear_calls = 0
        self.visible = visible
        self.scene_loads = []
        self.scene_refreshes = []
        self.scene_failures = []
        self.discarded_camera_states = []
        self.plan_texture_updates = 0

    def apply_mesh_data(self, *args, **mesh_options):
        self.mesh_calls.append((args, mesh_options))

    def clear_scene(self):
        self.clear_calls += 1

    def begin_scene_load(self, bid_ref):
        self.scene_loads.append(bid_ref)

    def prepare_scene_refresh(self, bid_ref, page_uids):
        self.scene_refreshes.append((bid_ref, tuple(page_uids)))

    def apply_scene_failure(self, scene_identity):
        self.scene_failures.append(scene_identity)

    def discard_saved_camera_states(self, *, bid_ref=None, file_path=None):
        self.discarded_camera_states.append((bid_ref, file_path))

    def update_plan_texture(self):
        self.plan_texture_updates += 1

    def isVisible(self):
        return self.visible


class FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)


class _CollaborationStatusPanel:
    def __init__(self):
        self.states = []
        self.mutation_states = []
        self.presence_states = []
        self.page_info = ""
        self.page_info_states = []

    def set_page_info(self, message):
        self.page_info = message
        self.page_info_states.append(message)

    def set_collaboration_state(self, state, message=""):
        self.states.append((state, message))

    def set_collaboration_mutation_state(self, state, pending_count, message=""):
        self.mutation_states.append((state, pending_count, message))

    def set_collaboration_presence(self, users):
        self.presence_states.append(list(users))


class FakeConstructedMeshWindow:
    def __init__(self, *args, **_window_options):
        self.mesh_calls = []
        self.visible = True
        self.destroyed = FakeSignal()
        self.mesh_clicked = FakeSignal()
        self.elements_deleted = FakeSignal()
        self.assign_to_area_requested = FakeSignal()
        self.reassign_condition_requested = FakeSignal()
        self.set_negative_requested = FakeSignal()
        self.set_curved_requested = FakeSignal()
        self.overlay_display_mode_requested = FakeSignal()
        self.undo_requested = FakeSignal()
        self.redo_requested = FakeSignal()
        self.scene_refreshes = []
        self.scene_failures = []

    def set_context_menu_command_handlers(self, *args):
        pass

    def set_pick_enabled(self, _enabled):
        pass

    def set_editing_enabled(self, _enabled):
        pass

    def show_initial_window(self):
        self.visible = True

    def close(self):
        self.visible = False

    def apply_mesh_data(self, *args, **mesh_options):
        self.mesh_calls.append((args, mesh_options))

    def prepare_scene_refresh(self, bid_ref, page_uids):
        self.scene_refreshes.append((bid_ref, tuple(page_uids)))

    def apply_scene_failure(self, scene_identity):
        self.scene_failures.append(scene_identity)

    def clear_scene(self):
        self.visible = False

    def isVisible(self):
        return self.visible

    def set_overlay_display_mode(self, mode):
        pass


class FakeMeshPlanSignaler:
    def __init__(self):
        self.requests = 0

    def request(self):
        self.requests += 1


class FakeMeshAccess:
    def is_allowed(self, feature):
        return feature == Feature.VIEW_3D


class FakeSidebar:
    def __init__(self):
        self.quantity_updates = 0
        self.condition_quantity_updates = []
        self.condition_refreshes = 0
        self.condition_summary_loads = 0
        self.clears = 0

    def update_conditions_quantities(self, condition_uids=None):
        self.quantity_updates += 1
        self.condition_quantity_updates.append(
            None if condition_uids is None else list(condition_uids)
        )

    def refresh_conditions_ui(self):
        self.condition_refreshes += 1

    def load_condition_summary(self):
        self.condition_summary_loads += 1

    def clear_sidebars(self):
        self.clears += 1


class FakeToolbar:
    def __init__(self):
        self.refreshes = 0
        self.select_checked = 0
        self.takeoff_2d_active = True

    def refresh(self):
        self.refreshes += 1

    def set_select_checked(self):
        self.select_checked += 1

    def is_takeoff_2d_view_active(self):
        return self.takeoff_2d_active


class FakeMenuController:
    def __init__(self):
        self.updates = 0

    def update_menu_states(self):
        self.updates += 1

    def trigger_menu_action(self, action_id):
        pass

    def get_menu_action_state(self, action_id):
        return None


class FakeMainWindow:
    def __init__(self):
        self.menu_controller = FakeMenuController()
        self.project_view = FakeProjectView()
        self.title_refreshes = 0

    def refresh_window_title(self):
        self.title_refreshes += 1

    def set_database_window_title(self, _file_path):
        self.title_refreshes += 1


class FakeProjectView:
    def __init__(self):
        self.builds = 0
        self.resets = 0
        self.restored_project = None
        self.restored_file = None
        self.loaded_files = []
        self.restored_bid = None
        self.selected_node = None
        self.selection_notifications = 0

    def build_complete_structure(self, loaded_files):
        self.builds += 1
        self.loaded_files = list(loaded_files)

    def reset(self):
        self.resets += 1

    def restore_project_selection(self, project_uid, file_path=None):
        self.restored_project = (project_uid, file_path)

    def restore_file_selection(self, file_path):
        self.restored_file = file_path

    def restore_bid_selection(self, bid_ref):
        self.restored_bid = bid_ref
        self.selected_node = {
            "kind": "bid",
            "file_path": bid_ref.file_path,
            "bid_uid": bid_ref.bid_uid,
        }

    def notify_current_selection(self):
        self.selection_notifications += 1

    def get_selected_node_state(self):
        return self.selected_node


class FakeUnloadMainWindow:
    def __init__(self):
        self.menu_controller = FakeMenuController()
        self.project_view = FakeProjectView()
        self.title_refreshes = 0
        self.database_title_paths = []

    def refresh_window_title(self):
        self.title_refreshes += 1

    def set_database_window_title(self, file_path):
        self.database_title_paths.append(file_path)


class FakeTabWidget:
    def __init__(self, index=1):
        self.index = index
        self.visibility = []

    def setTabVisible(self, tab_index, visible):
        self.visibility.append((tab_index, visible))

    def currentIndex(self):
        return self.index

    def count(self):
        return 3

    def setCurrentIndex(self, index):
        self.index = index


class FakeViewStack:
    def __init__(self, index=1):
        self.index = index

    def currentIndex(self):
        return self.index

    def setCurrentIndex(self, index):
        self.index = index


class FakeUnloadUiState:
    def __init__(self, selected_file_path="active.mdb"):
        self._selected_file_path = selected_file_path
        self.reset_count = 0

    @property
    def selected_file_path(self):
        return self._selected_file_path

    def reset_selections(self):
        self.reset_count += 1
        self._selected_file_path = None

    def set_database_selected(self, *_args):
        pass

    def get_selected_bid_ref(self):
        return None


class FakeUnloadProjectData:
    def __init__(self, current_file_path="active.mdb", project_uids=None):
        self.current_file_path = current_file_path
        self.project_uids = list(project_uids or [])
        self.clear_page_selection_count = 0

    def get_current_file_path(self):
        return self.current_file_path

    def get_hierarchy(self):
        projects = {uid: HierarchyProjectInfo(name=uid) for uid in self.project_uids}
        return HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path="active.mdb",
                    display_name="active.mdb",
                    bid_projects=projects,
                )
            ]
        )

    def clear_page_selection(self):
        self.clear_page_selection_count += 1


class FakePlacement:
    def __init__(self):
        self.force_exit_count = 0
        self.enter_calls = []
        self.is_active = False
        self.condition_uid = None

    def force_exit(self):
        self.force_exit_count += 1
        self.is_active = False

    def enter(self, condition_uid, condition_uids):
        self.enter_calls.append((condition_uid, list(condition_uids)))
        self.condition_uid = condition_uid
        self.is_active = True
        return True


class FakeAccess:
    def __init__(self):
        self.refreshes = 0

    def refresh(self):
        self.refreshes += 1


class FakeUnloadViewer:
    def __init__(self):
        self.clears = 0

    def clear_plan_view(self):
        self.clears += 1


class FakeVisualization:
    def __init__(self, pending_mesh_scene_identity=None):
        self.mesh_pages = []
        self.monitoring_stopped = 0
        self.monitoring_started = 0
        self.cancelled_mesh_refreshes = 0
        self.pending_mesh_scene_identity = pending_mesh_scene_identity

    def refresh_mesh_view(self, page_uids):
        self.mesh_pages.append(list(page_uids))

    def get_pending_mesh_scene_identity(self):
        return self.pending_mesh_scene_identity

    def cancel_mesh_view_refresh(self):
        self.cancelled_mesh_refreshes += 1
        self.pending_mesh_scene_identity = None

    def stop_database_monitoring(self):
        self.monitoring_stopped += 1

    def start_database_monitoring(self):
        self.monitoring_started += 1


def configure_mesh_state(
    coordinator,
    *,
    tab_index=TAB_INDEX_TAKEOFF,
    view_index=1,
    opengl_viewer=None,
    mesh_window=None,
    visualization=None,
    last_mesh_scene=None,
):
    coordinator._tab_widget = FakeTabWidget(index=tab_index)
    coordinator._view_stack = FakeViewStack(index=view_index)
    coordinator._mesh_window = mesh_window
    coordinator.opengl_viewer = opengl_viewer
    coordinator._plan_texture_provider = None
    coordinator.visualization_service = visualization or FakeVisualization()
    coordinator._mesh_scene_dirty = False
    coordinator._dirty_mesh_page_uids = set()
    coordinator._pending_dirty_mesh_refresh = False
    coordinator._last_mesh_scene = last_mesh_scene
    coordinator._is_cleaning_up = False
    coordinator.ui_access_manager = FakeMeshAccess()


def scene_identity(bid_ref, generation, page_uids=("page-1",)):
    return MeshSceneIdentity(bid_ref, tuple(page_uids), generation)


def mesh_geometry(page_uid, floor_elevation, takeoff_uid="takeoff-1"):
    return MeshGeometry(
        vertices=[
            0.0,
            0.0,
            float(floor_elevation) + 2.0,
            1.0,
            1.0,
            float(floor_elevation),
        ],
        normals=[0.0, 1.0, 0.0],
        indices=[0, 1, 2],
        color="#123456",
        opacity=0.75,
        page_uid=page_uid,
        condition_uid="condition-1",
        takeoff_uid=takeoff_uid,
    )


class FakeUndo:
    def __init__(self):
        self.active = []

    def set_active_bid(self, bid_ref):
        self.active.append(bid_ref)


class FakeNav:
    def __init__(self):
        self.state = None

    def transition_to(self, state):
        self.state = state

    @property
    def is_refreshing(self):
        return False


class FakeRefreshUiState:
    def __init__(self):
        self.reset_count = 0
        self.database_selected = None
        self.bid_ref = object()

    def reset_selections(self):
        self.reset_count += 1
        self.bid_ref = None

    def set_database_selected(self, selected, file_path=None):
        self.database_selected = (selected, file_path)

    def set_bid_selection(self, bid_ref):
        self.bid_ref = bid_ref

    def get_selected_bid_ref(self):
        return self.bid_ref


class FakeRefreshSnapshot:
    def __init__(
        self,
        *,
        bid_ref=None,
        project_uid=None,
        database_selected=False,
        selected_file_path="active.mdb",
    ):
        self.bid_ref = bid_ref
        self.project_uid = project_uid
        self.database_selected = database_selected
        self.selected_file_path = selected_file_path


class FakeRefreshNav:
    def __init__(self, snapshot):
        self.refresh_snapshot = snapshot
        self.state = None
        self.transitions = []

    def finish_refresh(self, state):
        self.state = state

    def transition_to(self, state):
        self.transitions.append(state)
        self.state = state
        return True


class ImmediateNavigationOperations:
    def navigation_load_in_progress(self):
        return False

    def cancel_navigation_load(self, _database_id=""):
        pass

    def request_load_bid(self, bid_ref, completion):
        try:
            success = self.load_bid(bid_ref)
        except Exception as exc:
            completion(False, str(exc))
            return False
        completion(bool(success), "")
        return False


class DeferredNavigationOperations:
    def __init__(self):
        self.loading = False
        self.completion = None

    def navigation_load_in_progress(self):
        return self.loading

    def cancel_navigation_load(self, _database_id=""):
        self.loading = False
        self.completion = None

    def request_load_bid(self, _bid_ref, completion):
        self.loading = True
        self.completion = completion
        return True

    def complete(self, success, message=""):
        completion = self.completion
        self.loading = False
        self.completion = None
        completion(success, message)


class NavigationStatusUiState:
    def __init__(self):
        self.bid_ref = None
        self.selected_page_uids = []
        self.active_page_uid = None
        self.selected_file_path = "sql-database"

    def get_selected_bid_ref(self):
        return self.bid_ref

    def set_bid_selection(self, bid_ref):
        self.bid_ref = bid_ref

    def set_database_selected(self, _selected, file_path=None):
        self.selected_file_path = file_path

    def set_file_path(self, file_path):
        self.selected_file_path = file_path

    def set_page_selection(self, page_uids):
        self.selected_page_uids = list(page_uids)

    def reset_selections(self):
        self.bid_ref = None
        self.selected_page_uids = []
        self.active_page_uid = None

    def set_project_uid(self, _project_uid):
        pass


class NavigationStatusProjectData:
    def __init__(self):
        self.current_file_path = "sql-database"
        self.pages = {"page-1": SimpleNamespace(name="Page One")}

    def get_current_file_path(self):
        return self.current_file_path

    def set_current_file(self, file_path):
        self.current_file_path = file_path

    def clear_bid(self):
        pass

    def deselect_pages(self):
        pass

    def get_page(self, page_uid):
        return self.pages.get(page_uid)


def navigation_status_coordinator(tab_index=TAB_INDEX_PROJECTS):
    coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
    coordinator._is_cleaning_up = False
    coordinator.project_operations = DeferredNavigationOperations()
    coordinator._status_panel = _CollaborationStatusPanel()
    coordinator._tab_widget = FakeTabWidget(index=tab_index)
    coordinator._view_stack = FakeViewStack(index=1)
    coordinator.opengl_viewer = None
    coordinator.ui_state_manager = NavigationStatusUiState()
    coordinator.project_data = NavigationStatusProjectData()
    coordinator.main_window = FakeUnloadMainWindow()
    coordinator._sql_collaboration = FakeSqlCollaboration()
    coordinator._plan_view_handler = None
    coordinator._placement = FakePlacement()
    coordinator._viewer = FakeUnloadViewer()
    coordinator._nav = FakeNav()
    coordinator.ui_access_manager = FakeAccess()
    coordinator._save_current_page_view_state = lambda: None
    coordinator._sync_undo_bid = lambda: None
    coordinator._clear_mesh_views_for_scene_update = lambda **_options: None
    coordinator._reset_takeoff_workspace_state = lambda: None
    coordinator._update_export_menu_state = lambda: None
    coordinator._update_menu_state = lambda: None
    coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
    coordinator._begin_mesh_views_for_bid_load = lambda _bid_ref: None
    coordinator._resolve_bid_lock_state = lambda _bid_ref: None
    coordinator.ensure_select_mode = lambda: None
    coordinator._activate_takeoff_workspace = coordinator._sync_page_info_status
    coordinator._load_condition_summary = lambda: None
    return coordinator


class UIEventCoordinatorTakeoffsChangedTests(unittest.TestCase):
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

    def test_remote_conditions_update_uses_ui_state_mutation_contract(self):
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
        coordinator.ui_state_manager = ui_state
        mesh_refreshes = []
        coordinator.project_data = SimpleNamespace(
            get_bid_conditions=lambda: {"c1": object()},
            get_selected_page_uids=lambda: ["page-1"],
        )
        coordinator._undo_service = None
        coordinator._sidebar = SimpleNamespace(
            refresh_conditions_from_memory=lambda: None
        )
        coordinator.highlight_sidebar = lambda _uids, reveal=False: None
        coordinator._update_plan_view_for_active = lambda **_kwargs: None
        coordinator._request_or_defer_mesh_refresh = (
            lambda pages: mesh_refreshes.append(list(pages))
        )
        coordinator._update_export_menu_state = lambda: None
        coordinator._on_remote_conditions_changed(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            condition_uids=["c1"],
        )
        self.assertEqual(ui_state.highlighted_condition_uids, {"c1"})
        self.assertEqual(mesh_refreshes, [["page-1"]])

    def test_remote_area_change_refreshes_3d_even_without_page_settings_bar(self):
        bid_ref = BidRef("sql-database", "bid-1")
        mesh_refreshes = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
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

    def test_stale_sql_failure_does_not_replace_active_access_selection(self):
        panel = _CollaborationStatusPanel()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._pending_takeoff_page_uids = None
        coordinator.ui_state_manager = SimpleNamespace(
            selected_file_path="C:/projects/active.mdb"
        )
        coordinator._status_panel = panel
        coordinator._plan_view_handler = None
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

    def test_selected_sql_failure_projects_disconnected_state(self):
        panel = _CollaborationStatusPanel()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._pending_takeoff_page_uids = None
        coordinator.ui_state_manager = SimpleNamespace(
            selected_file_path="sql-database-id"
        )
        coordinator._status_panel = panel
        hidden_previews = []
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

    def test_denied_collaboration_lease_reports_the_store_message(self):
        sequence = []
        callbacks = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.main_window = object()
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
        coordinator.event_bus = object()
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
            prepare_for_modal_mutation_error=lambda: sequence.append("pointer")
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

        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator.SynchronizationConflictDialog",
            return_value=dialog,
        ), patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator.exec_with_ost_blocking",
            side_effect=execute,
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

    def test_inactive_database_lease_loss_cancels_only_its_deferred_writes(self):
        cancelled = []
        placement_exits = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = type(
            "UiState",
            (),
            {"selected_file_path": "active-database"},
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
        coordinator._placement = type(
            "Placement",
            (),
            {"force_exit": lambda _self: placement_exits.append(True)},
        )()
        coordinator._on_edit_lease_lost(
            EditLeaseLoss(
                database_id="inactive-database",
                draft_id="draft",
                runtime_generation=1,
                operation_id="edit-condition",
                owning_surface="detached-view",
                resources=(ResourceRef("condition", "42", 8),),
                reason="trust-lost",
            )
        )
        self.assertEqual(cancelled, ["inactive-database"])
        self.assertEqual(placement_exits, [])

    def _make_page_selection_coordinator(self, *, bid_ref=None, current_state=None):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        nav = NavigationStateMachine()
        if current_state is not None:
            nav.transition_to(NavState.FILE_LOADED_NO_BID)
            if current_state == NavState.BID_ACTIVE_NO_PAGES:
                nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)
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

    def test_shared_void_callback_cleanup_releases_callback(self):
        calls = []
        signaler = QtVoidCallback()
        callback = lambda: calls.append("called")
        signaler.set_callback(callback)
        signaler.cleanup()
        signaler.request()
        self.assertEqual(calls, [])
        self.assertIsNone(signaler._callback)

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
        coordinator.plan_view = object()
        coordinator._is_cleaning_up = False
        coordinator._undo_service = None
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
            resource_uids_by_family={
                CollaborationResourceFamily.TAKEOFFS.value: ("takeoff-1",)
            },
            barrier=barrier,
        )
        barrier.seal()
        self.assertEqual(len(coordinator._viewer.remote_requests), 1)
        self.assertEqual(coordinator.visualization_service.mesh_pages, [["page-1"]])
        self.assertEqual(completed, [True])

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
        coordinator.ui_state_manager = SelectedUiState()
        coordinator.project_data = ProjectDataService(model)
        coordinator._undo_service = None
        coordinator._sidebar = sidebar
        mesh_refreshes = []
        coordinator._request_or_defer_mesh_refresh = (
            lambda pages: mesh_refreshes.append(list(pages))
        )
        coordinator._update_plan_view_for_active = lambda: None
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

    def test_remote_page_removal_republishes_scene_for_remaining_checked_pages(self):
        bid_ref = BidRef("sql-db", "bid-1")
        remaining_page = Page(uid="page-a", name="Page A", sequence=1)
        selected_pages = []
        mesh_refreshes = []
        terminal_clears = []
        restored_navigation = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._pending_takeoff_page_uids = None
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

    def test_stale_page_family_completion_reprojects_latest_navigation(self):
        bid_ref = BidRef("sql-db", "bid-1")
        pages = {
            "page-a": Page(uid="page-a", name="Page A", sequence=1),
            "page-b": Page(uid="page-b", name="Page B", sequence=2),
        }
        restored_navigation = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._pending_takeoff_page_uids = None
        coordinator.ui_state_manager = SimpleNamespace(
            selected_page_uids=["page-b"],
            active_page_uid="page-b",
            get_selected_bid_ref=lambda: bid_ref,
            set_page_selection=lambda selected: setattr(
                coordinator.ui_state_manager,
                "selected_page_uids",
                list(selected),
            ),
        )
        coordinator.project_data = SimpleNamespace(
            get_page=pages.get,
            get_all_pages=lambda: list(pages.values()),
            select_pages=lambda selected: list(selected),
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

    def test_remote_removal_of_all_checked_pages_publishes_recoverable_empty_scene(
        self,
    ):
        bid_ref = BidRef("sql-db", "bid-1")
        mesh_refreshes = []
        terminal_clears = []
        restored_navigation = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._pending_takeoff_page_uids = None
        coordinator.ui_state_manager = SimpleNamespace(
            selected_page_uids=["deleted-page"],
            active_page_uid="deleted-page",
            get_selected_bid_ref=lambda: bid_ref,
            set_page_selection=lambda _pages: None,
        )
        coordinator.project_data = SimpleNamespace(
            get_page=lambda _uid: None,
            get_all_pages=lambda: [],
            select_pages=lambda pages: list(pages),
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
        self.assertEqual(mesh_refreshes, [[]])
        self.assertEqual(terminal_clears, [])
        self.assertEqual(restored_navigation, [([], None)])

    def test_remote_projection_request_failure_releases_registered_surface(self):
        database_id = "sql-db"
        bid_uid = "bid-1"

        class SelectedUiState(FakeUiState):
            def get_selected_bid_ref(self):
                return BidRef(database_id, bid_uid)

        class RaisingViewer:
            def request_remote_plan_update(self, **_request):
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
                resource_uids_by_family={
                    CollaborationResourceFamily.TAKEOFFS.value: ("takeoff-1",)
                },
                barrier=barrier,
            )
        barrier.seal()
        self.assertEqual(mesh_refreshes, [["page-1"]])
        self.assertEqual(completed, [False])

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

    def test_hidden_2d_takeoff_changes_aggregate_dirty_pages_and_flush_on_3d(self):
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
        self.assertEqual(coordinator._dirty_mesh_page_uids, {"page-1", "page-2"})
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

    def test_opening_detached_mesh_window_with_dirty_state_requests_fresh_mesh(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = FakeUiState()
        coordinator.project_data = FakeProjectData()
        coordinator._icon_provider = None
        coordinator._color_service = None
        coordinator._plan_view_handler = None
        coordinator._mesh_window = None
        coordinator._mesh_window_action = None
        last_mesh_scene = _MeshScenePublication(
            ("stale",),
            {
                "scene_identity": scene_identity(BidRef("test.mdb", "bid-1"), 1),
                "page_floor_elevations": {"page-1": 1.0},
            },
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
        self.assertEqual(coordinator._mesh_window.mesh_calls, [])

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
        last_mesh_scene = _MeshScenePublication(
            mesh_args,
            {
                "scene_identity": scene_identity(active_ref, 1),
                "page_floor_elevations": {"page-1": 1.0},
            },
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
            last_mesh_scene=_MeshScenePublication(
                ("vertices", "normals", "indices", "colors"),
                {
                    "scene_identity": scene_identity(active_ref, 7, ("other-page",)),
                    "page_floor_elevations": {"other-page": 7.0},
                },
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
        publication = _MeshScenePublication(
            ("vertices", "normals", "indices", "colors"),
            {
                "scene_identity": scene_identity(active_ref, 7),
                "page_floor_elevations": {"page-1": 7.0},
            },
        )
        coordinator._last_mesh_scene = publication
        coordinator._on_view_stack_changed(0)
        self.assertEqual(
            embedded.scene_refreshes,
            [(active_ref, ("page-1",))],
        )
        self.assertEqual(embedded.mesh_calls, [(publication.args, publication.options)])
        embedded.scene_refreshes.clear()
        embedded.mesh_calls.clear()
        coordinator._last_mesh_scene = _MeshScenePublication(
            publication.args,
            {
                "scene_identity": scene_identity(BidRef("test.mdb", "stale-bid"), 8),
                "page_floor_elevations": {"page-1": 8.0},
            },
        )
        coordinator._on_view_stack_changed(0)
        self.assertEqual(embedded.scene_refreshes, [])
        self.assertEqual(embedded.mesh_calls, [])
        self.assertIsNone(coordinator._last_mesh_scene)

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
        self.assertEqual(coordinator._last_mesh_scene.args, args)
        self.assertEqual(coordinator._last_mesh_scene.options, mesh_options)
        self.assertEqual(mesh_window.mesh_calls, opengl_viewer.mesh_calls)
        self.assertEqual(1, coordinator._plan_view_signaler.requests)

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
            coordinator._last_mesh_scene.options["page_floor_elevations"],
            expected,
        )
        with self.assertRaises(TypeError):
            coordinator._last_mesh_scene.options["page_floor_elevations"][
                "page-a"
            ] = -100.0

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
        coordinator._last_mesh_scene = _MeshScenePublication(
            ("old",),
            {
                "scene_identity": scene_identity(BidRef("a.mdb", "old"), 1),
                "page_floor_elevations": {"page-1": 1.0},
            },
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

            def highlight_conditions(self, uids, reveal=True):
                self.highlights.append(set(uids))

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
        coordinator._selected_takeoff_condition_uids = set()
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

            def highlight_conditions(self, uids, reveal=True):
                self.highlights.append(set(uids))

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
        coordinator._selected_takeoff_condition_uids = set()
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

            def highlight_conditions(self, uids, reveal=True):
                self.highlights.append(set(uids))

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
        coordinator._selected_takeoff_condition_uids = set()
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

            def highlight_conditions(self, uids, reveal=True):
                self.highlights.append(set(uids))

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
        coordinator._selected_takeoff_condition_uids = set()
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
        self.assertEqual(coordinator._selected_takeoff_condition_uids, set())
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

            def highlight_conditions(self, uids, reveal=True):
                self.highlights.append(set(uids))

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
        coordinator._selected_takeoff_condition_uids = set()
        coordinator._selection_projected_condition_uids = set()
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1"])
        coordinator.ui_state_manager.set_highlighted_conditions(set())
        coordinator.conditions_sidebar.highlights.clear()
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1"])
        self.assertEqual(
            coordinator.ui_state_manager.highlighted_condition_uids, {"c1"}
        )
        self.assertEqual(coordinator.conditions_sidebar.highlights, [{"c1"}])

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

            def highlight_conditions(self, uids, reveal=True):
                self.highlights.append(set(uids))

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
        coordinator._selected_takeoff_condition_uids = set()
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
        coordinator.highlight_sidebar = lambda _uids, reveal=True: reveal_args.append(
            reveal
        )
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
        coordinator._selected_takeoff_condition_uids = set()
        coordinator._selection_projected_condition_uids = set()
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1"])
        coordinator._sync_selection(coordinator._SOURCE_2D, [])
        self.assertEqual(
            coordinator.ui_state_manager.highlighted_condition_uids, {"c1"}
        )

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
        coordinator._selected_takeoff_condition_uids = {"c1", "c2"}
        coordinator._selection_projected_condition_uids = {"c1", "c2"}
        configure_mesh_state(coordinator)
        coordinator._sync_page_info_status = lambda: None
        coordinator._on_view_stack_changed(0)
        self.assertEqual(coordinator._placement.force_exit_count, 1)
        self.assertIsNone(coordinator.ui_state_manager.place_condition_uid)
        self.assertEqual(coordinator._toolbar.select_checked, 1)
        self.assertEqual(coordinator._sidebar.quantity_updates, 1)
        self.assertEqual(coordinator._selected_takeoff_uids, ("t1", "t2"))
        self.assertEqual(coordinator._selected_takeoff_condition_uids, {"c1", "c2"})

    def test_late_view_stack_signal_after_cleanup_is_ignored(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = True
        coordinator._placement = None
        coordinator._toolbar = None
        coordinator._sidebar = None
        coordinator.ui_state_manager = None
        coordinator.plan_view = None
        coordinator._on_view_stack_changed(0)

    def test_completed_background_bid_load_clears_loading_status_on_projects_tab(self):
        coordinator = navigation_status_coordinator()
        coordinator.handle_bid_selection(BidRef("sql-database", "bid-1"))
        self.assertEqual(coordinator._status_panel.page_info, "Loading bid pages…")
        coordinator.project_operations.complete(True)
        self.assertEqual(coordinator._status_panel.page_info, "")

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

    def test_cancelling_bid_load_clears_loading_status(self):
        coordinator = navigation_status_coordinator()
        coordinator.handle_bid_selection(BidRef("sql-database", "bid-1"))
        self.assertEqual(coordinator._status_panel.page_info, "Loading bid pages…")
        coordinator.handle_bid_selection(None)
        self.assertFalse(coordinator.project_operations.navigation_load_in_progress())
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
        coordinator._viewer = FakeUnloadViewer()
        coordinator.visualization_service = FakeVisualization()
        coordinator.ui_access_manager = FakeAccess()
        coordinator._update_export_menu_state = lambda: None
        coordinator._save_current_page_view_state = lambda: None
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
        coordinator._clear_mesh_views_for_scene_update = lambda **_call_options: None
        coordinator._reset_takeoff_workspace_state = lambda: None
        coordinator._set_takeoff_tab_visible = lambda _visible: None
        coordinator.handle_bid_selection(None)
        self.assertIsNone(coordinator.ui_state_manager.get_selected_bid_ref())
        self.assertEqual(coordinator._undo_service.active, [None])
        self.assertEqual(clear_bid_calls, [True])

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

    def _make_unload_coordinator(
        self, selected_file="active.mdb", current_file="active.mdb"
    ):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
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
        coordinator._sidebar = FakeSidebar()
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator.visualization_service = FakeVisualization()
        coordinator._tab_widget = FakeTabWidget(index=1)
        coordinator._toolbar = FakeToolbar()
        coordinator._nav = FakeNav()
        coordinator._bid_data_cache = {}
        coordinator._takeoff_workspace_bid_ref = None
        coordinator._pending_takeoff_page_uids = None
        coordinator._pending_takeoff_active_page_uid = None
        coordinator._pending_takeoff_selected_area_uid = ""
        coordinator._pending_takeoff_place_condition_uid = None
        coordinator._pending_takeoff_place_condition_uids = []
        coordinator._selected_takeoff_uids = ()
        coordinator._selected_takeoff_condition_uids = set()
        coordinator._selection_projected_condition_uids = set()
        coordinator._page_settings_bar = None
        coordinator._mesh_scene_dirty = False
        coordinator._dirty_mesh_page_uids = set()
        coordinator._pending_dirty_mesh_refresh = False
        coordinator._clear_mesh_replay_buffer = lambda: None
        return coordinator

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
        coordinator.opengl_viewer = embedded
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
        self.assertEqual(
            embedded.discarded_camera_states,
            [(None, "active.mdb")],
        )
        self.assertEqual(status_panel.page_info, "")
        self.assertEqual(status_panel.presence_states[-1], [])
        self.assertEqual(status_panel.mutation_states[-1], ("", 0, ""))
        self.assertEqual(status_panel.states[-1], ("stopped", ""))

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
        coordinator._selected_takeoff_condition_uids = {"c1"}
        coordinator._selection_projected_condition_uids = {"c1"}
        coordinator._resolve_bid_lock_state = lambda _bid_ref: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._activate_takeoff_workspace = lambda: None
        coordinator._nav = Nav()
        coordinator._finish_refresh()
        self.assertEqual(coordinator._sidebar.clears, 0)
        self.assertIsNone(coordinator._takeoff_workspace_bid_ref)
        self.assertEqual(coordinator._selected_takeoff_uids, ("t1",))
        self.assertEqual(coordinator._selected_takeoff_condition_uids, {"c1"})
        self.assertEqual(coordinator._selection_projected_condition_uids, {"c1"})

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

    def test_database_refresh_drops_permanently_deleted_bid_and_hides_takeoff(self):
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
        coordinator._update_export_menu_state = lambda: None
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


if __name__ == "__main__":
    unittest.main()
