import unittest
from ost_visualizer.application.dtos.collaboration_dtos import (
    CollaborationStatus,
    EditLeaseResult,
    SynchronizationState,
)
from ost_visualizer.application.dtos.mesh_geometry_dto import MeshGeometry
from ost_visualizer.application.services.project_write_service import WriteReloadResult
from ost_visualizer.domain.entities.annotation import ANNOTATION_TYPE_TEXT
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from ost_visualizer.presentation.coordinators.navigation_state_machine import (
    NavigationStateMachine,
    NavState,
)
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
    _MainThreadSignaler,
)
from ost_visualizer.presentation.managers.ui_access_manager import Feature


class FakeUiState:
    active_page_uid = "page-1"
    place_condition_uid = None

    def get_selected_bid_ref(self):
        return None

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


class FakeMeshReceiver:
    def __init__(self, visible=True):
        self.mesh_calls = []
        self.clear_calls = 0
        self.visible = visible

    def apply_mesh_data(self, *args, **mesh_options):
        self.mesh_calls.append((args, mesh_options))

    def clear_scene(self):
        self.clear_calls += 1

    def isVisible(self):
        return self.visible


class FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)


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

    def set_context_menu_command_handlers(self, *args):
        pass

    def set_pick_enabled(self, _enabled):
        pass

    def set_editing_enabled(self, _enabled):
        pass

    def show_initial_window(self):
        self.visible = True

    def apply_mesh_data(self, *args, **mesh_options):
        self.mesh_calls.append((args, mesh_options))

    def isVisible(self):
        return self.visible

    def set_overlay_display_mode(self, mode):
        pass


class FakeMeshPlanSignaler:
    def __init__(self):
        self.requests = 0

    def request_update(self):
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

    def clear_viewer(self):
        self.clears += 1


class FakeVisualization:
    def __init__(self):
        self.mesh_pages = []
        self.monitoring_stopped = 0
        self.monitoring_started = 0

    def refresh_mesh_view(self, page_uids):
        self.mesh_pages.append(list(page_uids))

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


class UIEventCoordinatorTakeoffsChangedTests(unittest.TestCase):
    def test_denied_collaboration_lease_reports_the_store_message(self):
        warnings = []
        callbacks = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.main_window = object()
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
        ui_event_coordinator.show_warning = lambda *args: warnings.append(args)
        try:
            coordinator.request_collaboration_edit(
                "database",
                (),
                callbacks.append,
            )
        finally:
            ui_event_coordinator.show_warning = old_warning
        self.assertEqual(callbacks, [False])
        self.assertEqual(len(warnings), 1)
        self.assertIn("already being edited", warnings[0][2])

    def test_late_collaboration_lease_grant_is_denied_during_cleanup(self):
        callbacks = []
        warnings = []
        pending = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.main_window = object()
        coordinator._sql_collaboration = type(
            "SqlCollaboration",
            (),
            {
                "request_local_edit": lambda _self, _database_id, _resources, callback, **_kwargs: pending.append(
                    callback
                )
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
            pending[0](EditLeaseResult(True))
        finally:
            ui_event_coordinator.show_warning = old_warning
        self.assertEqual(callbacks, [False])
        self.assertEqual(warnings, [])

    def test_inactive_database_reconciliation_does_not_replace_active_project_state(
        self,
    ):
        reloads = []
        cancelled = []
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
        coordinator.main_window = object()
        coordinator._on_full_reconciliation_required("inactive-database", "gap")
        self.assertEqual(cancelled, ["inactive-database"])
        self.assertEqual(reloads, [])

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
        coordinator._on_edit_lease_lost("inactive-database")
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
        coordinator._update_page_info_status = lambda: None
        return coordinator

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

    def test_page_selection_from_file_state_steps_through_bid_no_pages(self):
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
            NavState.BID_ACTIVE_PAGES_SELECTED,
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

    def test_main_thread_signaler_cleanup_releases_callback(self):
        calls = []
        signaler = _MainThreadSignaler()
        callback = lambda: calls.append("called")
        signaler.set_callback(callback)
        signaler.cleanup()
        signaler.request_update()
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

    def test_takeoffs_changed_loads_summary_when_summary_tab_is_active(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
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

    def test_takeoffs_changed_keeps_empty_model_selection_for_mesh_refresh(self):
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
        coordinator._update_page_info_status = lambda: None
        coordinator._on_takeoffs_changed(page_uid="page-1", takeoff_uids=["t-1"])
        coordinator._on_takeoffs_changed(page_uid="page-2", takeoff_uids=["t-2"])
        self.assertEqual(coordinator.visualization_service.mesh_pages, [])
        self.assertEqual(coordinator._dirty_mesh_page_uids, {"page-1", "page-2"})
        coordinator._view_stack.setCurrentIndex(0)
        coordinator._on_view_stack_changed(0)
        self.assertEqual(coordinator.visualization_service.mesh_pages, [["page-1"]])
        self.assertTrue(coordinator._pending_dirty_mesh_refresh)
        coordinator._on_native_scene_updated(geometries=[])
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
        coordinator._last_mesh_args = ("stale",)
        coordinator._last_mesh_options = {"bid_ref": None}
        coordinator.ui_access_manager = FakeMeshAccess()
        coordinator.main_window = FakeMainWindow()
        configure_mesh_state(coordinator)
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
        coordinator._last_mesh_args = ("vertices", "normals", "indices", "colors")
        coordinator._last_mesh_options = {"bid_ref": None}
        coordinator.ui_access_manager = FakeMeshAccess()
        coordinator.main_window = FakeMainWindow()
        configure_mesh_state(coordinator)
        from ost_visualizer.presentation.coordinators import ui_event_coordinator

        original = ui_event_coordinator.MeshViewWindow
        ui_event_coordinator.MeshViewWindow = FakeConstructedMeshWindow
        try:
            coordinator.set_mesh_window_visible(True)
        finally:
            ui_event_coordinator.MeshViewWindow = original
        self.assertEqual(coordinator.visualization_service.mesh_pages, [])
        self.assertEqual(len(coordinator._mesh_window.mesh_calls), 1)

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
        coordinator._last_mesh_args = None
        coordinator._last_mesh_options = None
        geometry = MeshGeometry(
            vertices=[0.0, 0.0, 0.0],
            normals=[0.0, 1.0, 0.0],
            indices=[0, 1, 2],
            color="#123456",
            opacity=0.75,
            condition_uid="condition-1",
            takeoff_uid="takeoff-1",
        )
        coordinator._on_native_scene_updated(
            geometries=[geometry], bounds=(-1, 1, -2, 2, -3, 3)
        )
        self.assertEqual(1, len(coordinator.opengl_viewer.mesh_calls))
        args, mesh_options = coordinator.opengl_viewer.mesh_calls[0]
        self.assertEqual(([[0.0, 0.0, 0.0]], [[0.0, 1.0, 0.0]], [[0, 1, 2]]), args[:3])
        self.assertEqual([{"color": "#123456", "opacity": 0.75}], args[3])
        self.assertEqual(["condition-1"], mesh_options["condition_uids"])
        self.assertEqual(["takeoff-1"], mesh_options["takeoff_uids"])
        self.assertEqual((-1, 1, -2, 2, -3, 3), mesh_options["scene_bounds"])
        self.assertEqual(coordinator._last_mesh_args, args)
        self.assertEqual(coordinator._last_mesh_options, mesh_options)
        self.assertEqual(1, coordinator._plan_view_signaler.requests)

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

    def test_clearing_takeoff_selection_keeps_takeoff_selected_condition(self):
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
        coordinator._last_takeoff_selection_context_by_source = {}
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1"])
        coordinator._sync_selection(coordinator._SOURCE_2D, [])
        self.assertEqual(
            coordinator.ui_state_manager.highlighted_condition_uids, {"c1"}
        )
        self.assertEqual(coordinator.conditions_sidebar.highlights, [{"c1"}])

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
        coordinator._last_takeoff_selection_context_by_source = {}
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1"])
        coordinator.highlight_sidebar({"c2"})
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1"])
        self.assertEqual(
            coordinator.ui_state_manager.highlighted_condition_uids, {"c2"}
        )
        self.assertEqual(coordinator.conditions_sidebar.highlights, [{"c1"}, {"c2"}])

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
        coordinator._last_takeoff_selection_context_by_source = {}
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
        coordinator._last_takeoff_selection_context_by_source = {}
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

    def test_late_takeoff_selection_signal_after_cleanup_is_ignored(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._placement = None
        coordinator._nav = None
        coordinator._on_takeoff_selection_changed(["t1"])

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
        coordinator._last_takeoff_selection_context_by_source = {}
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
        configure_mesh_state(coordinator)
        coordinator._update_page_info_status = lambda: None
        coordinator._on_view_stack_changed(0)
        self.assertEqual(coordinator._placement.force_exit_count, 1)
        self.assertIsNone(coordinator.ui_state_manager.place_condition_uid)
        self.assertEqual(coordinator._toolbar.select_checked, 1)
        self.assertEqual(coordinator._sidebar.quantity_updates, 1)

    def test_late_view_stack_signal_after_cleanup_is_ignored(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = True
        coordinator._placement = None
        coordinator._toolbar = None
        coordinator._sidebar = None
        coordinator.ui_state_manager = None
        coordinator.plan_view = None
        coordinator._on_view_stack_changed(0)

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

        class ProjectOperations:
            def load_bid(self, bid_ref):
                self.requested = bid_ref
                return False

        class Undo:
            def __init__(self):
                self.active = []

            def set_active_bid(self, bid_ref):
                self.active.append(bid_ref)

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeUnloadMainWindow()
        coordinator._sql_collaboration = FakeSqlCollaboration()
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
        coordinator._sql_collaboration = FakeSqlCollaboration()
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
        coordinator._sql_collaboration = FakeSqlCollaboration()
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

    def _make_unload_coordinator(
        self, selected_file="active.mdb", current_file="active.mdb"
    ):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
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
        coordinator._last_takeoff_selection_context_by_source = {}
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
        coordinator._on_file_unloaded(
            file_path="inactive.mdb",
            active_context_removed=False,
        )
        self.assertEqual(coordinator.ui_state_manager.reset_count, 0)
        self.assertEqual(coordinator._viewer.clears, 0)
        self.assertEqual(coordinator._tab_widget.visibility, [])
        self.assertEqual(coordinator.main_window.project_view.builds, 1)
        self.assertEqual(coordinator.main_window.menu_controller.updates, 1)

    def test_active_file_unload_switches_to_projects_and_hides_takeoff(self):
        coordinator = self._make_unload_coordinator(
            selected_file="active.mdb",
            current_file=None,
        )
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

    def test_database_refresh_restores_database_root_selection_and_hides_takeoff(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
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

            def compute_state_for(self, has_file, bid_ref, page_uids, placement_active):
                return "BID_ACTIVE"

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeUnloadMainWindow()
        coordinator.ui_state_manager = UiState()
        coordinator._sql_collaboration = FakeSqlCollaboration()
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
        coordinator._last_takeoff_selection_context_by_source = {"2d": ["t1"]}
        coordinator._resolve_bid_lock_state = lambda _bid_ref: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._activate_takeoff_workspace = lambda: None
        coordinator._nav = Nav()
        coordinator._finish_refresh()
        self.assertEqual(coordinator._sidebar.clears, 0)
        self.assertIsNone(coordinator._takeoff_workspace_bid_ref)
        self.assertEqual(coordinator._last_takeoff_selection_context_by_source, {})

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

        class ProjectOperations:
            def __init__(self, project_data):
                self.project_data = project_data
                self.loaded = []

            def load_bid(self, bid_ref):
                self.loaded.append(bid_ref)
                self.project_data.current_bid_ref = bid_ref
                return True

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeUnloadMainWindow()
        coordinator.ui_state_manager = UiState()
        coordinator._sql_collaboration = FakeSqlCollaboration()
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
