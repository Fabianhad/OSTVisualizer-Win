import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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
from ost_visualizer.application.dtos.collaboration_resource_catalog import (
    CollaborationResourceFamily,
    CollaborationResourceType,
)
from ost_visualizer.application.dtos.conflict_resolution_dtos import (
    ConflictResolutionAction,
)
from ost_visualizer.application.dtos.mesh_geometry_dto import (
    MeshGeometry,
    MeshSceneIdentity,
)
from ost_visualizer.application.dtos.remote_projection_dtos import (
    RemoteProjectionBarrier,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.interfaces.i_database_catalog import (
    DatabaseCatalogError,
)
from ost_visualizer.application.services.project_write_service import WriteReloadResult
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
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
from ost_visualizer.presentation.coordinators.placement_coordinator import (
    PlacementCoordinator,
)
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
    _MeshScenePublication,
)
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.managers.ui_state_manager import UIStateManager
from ost_visualizer.presentation.modes.cursor import (
    CURSOR_MODE_PLACE,
    CURSOR_MODE_SELECT,
)
from ost_visualizer.presentation.services.bid_clipboard_service import (
    BidClipboardService,
)
from ost_visualizer.presentation.utils.qt_callback_bridge import QtVoidCallback
from PySide6 import QtWidgets
from shiboken6 import delete


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
        pass

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
        self.overlay_refresh_flags = []
        self.remote_requests = []

    def update_plan_view(
        self,
        page_uid,
        changed_takeoff_uids=None,
        changed_annotation_uids=None,
        changed_annotation_types=None,
        force_overlay_refresh=False,
    ):
        self.overlay_refresh_flags.append(force_overlay_refresh)
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
        request = {
            "database_id": database_id,
            "runtime_generation": runtime_generation,
            "bid_uid": bid_uid,
            "resource_uids_by_family": resource_uids_by_family,
            "barrier": barrier,
            "completion": completion,
        }
        self.remote_requests.append(request)
        completion(True)
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
        self.pending_mutation_uids = set()

    def apply_mesh_data(
        self,
        vertices,
        normals,
        indices,
        colors,
        *,
        scene_identity,
        page_floor_elevations,
        condition_uids,
        takeoff_uids,
    ):
        self.mesh_calls.append(
            (
                (vertices, normals, indices, colors),
                {
                    "scene_identity": scene_identity,
                    "page_floor_elevations": page_floor_elevations,
                    "condition_uids": condition_uids,
                    "takeoff_uids": takeoff_uids,
                },
            )
        )

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

    def set_pending_mutation_uids(self, takeoff_uids):
        self.pending_mutation_uids = set(takeoff_uids)

    def get_pending_mutation_uids(self):
        return set(self.pending_mutation_uids)

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
        self.pending_mutation_uids = set()

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

    def apply_mesh_data(
        self,
        vertices,
        normals,
        indices,
        colors,
        *,
        scene_identity,
        page_floor_elevations,
        condition_uids,
        takeoff_uids,
    ):
        self.mesh_calls.append(
            (
                (vertices, normals, indices, colors),
                {
                    "scene_identity": scene_identity,
                    "page_floor_elevations": page_floor_elevations,
                    "condition_uids": condition_uids,
                    "takeoff_uids": takeoff_uids,
                },
            )
        )

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

    def set_pending_mutation_uids(self, takeoff_uids):
        self.pending_mutation_uids = set(takeoff_uids)


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

    def load_condition_summary(self, grouping=None):
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
        self.bid_content_counts = []

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

    def update_bid_content_counts(self, bid_ref, **counts):
        self.bid_content_counts.append((bid_ref, counts))


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
        self.reconciliation_calls = 0

    def force_exit(self):
        self.force_exit_count += 1
        self.is_active = False

    def enter(self, condition_uid, condition_uids):
        self.enter_calls.append((condition_uid, list(condition_uids)))
        self.condition_uid = condition_uid
        self.is_active = True
        return True

    def reconcile_authoritative_conditions(
        self, *, accept_reconstructed_conditions=False
    ):
        _ = accept_reconstructed_conditions
        self.reconciliation_calls += 1
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
    coordinator._pending_3d_takeoff_uids_by_bid = {}
    coordinator._is_cleaning_up = False
    coordinator.ui_access_manager = FakeMeshAccess()


def scene_identity(bid_ref, generation, page_uids=("page-1",)):
    return MeshSceneIdentity(bid_ref, tuple(page_uids), generation)


def mesh_publication(mesh_args, identity, page_floor_elevations):
    vertices, normals, indices, colors = mesh_args
    return _MeshScenePublication(
        vertices=vertices,
        normals=normals,
        indices=indices,
        colors=colors,
        scene_identity=identity,
        page_floor_elevations=page_floor_elevations,
        condition_uids=[],
        takeoff_uids=[],
    )


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

    def begin_bid_load(self, has_file):
        if not has_file:
            return False
        if self.state is None:
            self.state = NavState.FILE_LOADED_NO_BID
        return True

    @staticmethod
    def compute_state_for(has_file, bid_ref, active_page_uid):
        return NavigationStateMachine().compute_state_for(
            has_file,
            bid_ref,
            active_page_uid,
        )

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

    def begin_bid_load(self, has_file):
        return bool(has_file)


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
    coordinator._flush_deferred_for_file = lambda _file_path: True
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
