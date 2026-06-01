import unittest
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.hierarchy_data import HierarchyData
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
    _MainThreadSignaler,
)


class FakeUiState:
    active_page_uid = "page-1"

    def get_selected_bid_ref(self):
        return None


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


class FakeViewer:
    def __init__(self):
        self.plan_pages = []
        self.viewer_pages = []

    def update_plan_view(self, page_uid):
        self.plan_pages.append(page_uid)

    def update_viewers(self, page_uids):
        self.viewer_pages.append(list(page_uids))


class FakeSidebar:
    def __init__(self):
        self.quantity_updates = 0
        self.clears = 0

    def update_conditions_quantities(self):
        self.quantity_updates += 1

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


class FakeMainWindow:
    def __init__(self):
        self.menu_controller = FakeMenuController()


class FakeProjectView:
    def __init__(self):
        self.builds = 0
        self.resets = 0
        self.restored_project = None
        self.restored_file = None

    def build_complete_structure(self, _loaded_files):
        self.builds += 1

    def reset(self):
        self.resets += 1

    def restore_project_selection(self, project_uid, file_path=None):
        self.restored_project = (project_uid, file_path)

    def restore_file_selection(self, file_path):
        self.restored_file = file_path


class FakeUnloadMainWindow:
    def __init__(self):
        self.menu_controller = FakeMenuController()
        self.project_view = FakeProjectView()


class FakeTabWidget:
    def __init__(self, index=1):
        self.index = index
        self.visibility = []

    def setTabVisible(self, tab_index, visible):
        self.visibility.append((tab_index, visible))

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
    def __init__(self, current_file_path="active.mdb"):
        self.current_file_path = current_file_path
        self.clear_page_selection_count = 0

    def get_current_file_path(self):
        return self.current_file_path

    def get_hierarchy(self):
        return HierarchyData()

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


class FakeNav:
    def __init__(self):
        self.state = None

    def transition_to(self, state):
        self.state = state


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

    def finish_refresh(self, state):
        self.state = state


class UIEventCoordinatorTakeoffsChangedTests(unittest.TestCase):
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
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        coordinator._on_takeoffs_changed(page_uid="page-1", takeoff_uids=["t-1"])
        self.assertEqual(coordinator.takeoff_sidebar.calls, [("page-1", True)])
        self.assertEqual(
            coordinator._page_settings_bar.calls,
            [({"0", "area-1"}, {"area-1"})],
        )
        self.assertEqual(coordinator._viewer.plan_pages, ["page-1"])
        self.assertEqual(coordinator._viewer.viewer_pages, [["page-1"]])
        self.assertEqual(coordinator._sidebar.quantity_updates, 1)
        self.assertEqual(coordinator.main_window.menu_controller.updates, 1)
        self.assertEqual(coordinator._toolbar.refreshes, 1)

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
        coordinator._takeoff_highlight_condition_uids = set()
        coordinator._on_condition_selected("c1")
        self.assertEqual(coordinator._placement.enter_calls, [])
        self.assertEqual(coordinator.plan_view.modes, ["select"])
        self.assertEqual(coordinator._toolbar.select_checked, 1)
        self.assertEqual(highlighted, [{"c1"}])

    def test_clearing_takeoff_selection_clears_takeoff_owned_condition_highlight(self):
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

            def highlight_conditions(self, uids):
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
        coordinator._takeoff_highlight_condition_uids = set()
        coordinator._sync_selection(coordinator._SOURCE_2D, ["t1"])
        coordinator._sync_selection(coordinator._SOURCE_2D, [])
        self.assertEqual(coordinator.ui_state_manager.highlighted_condition_uids, set())
        self.assertEqual(coordinator.conditions_sidebar.highlights, [{"c1"}, set()])

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
        coordinator._takeoff_highlight_condition_uids = set()
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
        coordinator._clear_mesh_views_for_scene_update = lambda **_kwargs: None
        coordinator.handle_bid_selection(new_ref)
        self.assertIs(coordinator.ui_state_manager.get_selected_bid_ref(), old_ref)
        self.assertEqual(coordinator.ui_state_manager.page_selection, ["page-1"])
        self.assertEqual(coordinator.project_data.current_file, "old.mdb")
        self.assertEqual(coordinator.project_data.deselects, 0)
        self.assertEqual(coordinator._viewer.clears, 0)
        self.assertEqual(coordinator._undo_service.active, [])

    def test_failed_page_delete_clears_pending_page_restore(self):
        from ost_visualizer.presentation.coordinators import ui_event_coordinator

        old_show_critical = ui_event_coordinator.show_critical
        ui_event_coordinator.show_critical = lambda *_args, **_kwargs: None
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
            coordinator.delete_current_page()
            self.assertIsNone(coordinator._pending_takeoff_page_uids)
            self.assertIsNone(coordinator._pending_takeoff_active_page_uid)
        finally:
            ui_event_coordinator.show_critical = old_show_critical

    def _make_unload_coordinator(
        self, selected_file="active.mdb", current_file="active.mdb"
    ):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
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
        coordinator._page_settings_bar = None
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
        self.assertEqual(coordinator._tab_widget.visibility, [(1, False)])
        self.assertEqual(coordinator._tab_widget.currentIndex(), 0)
        self.assertEqual(coordinator.main_window.project_view.resets, 1)
        self.assertEqual(coordinator.main_window.menu_controller.updates, 1)

    def test_database_refresh_restores_database_root_selection(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeUnloadMainWindow()
        coordinator.project_data = FakeUnloadProjectData("active.mdb")
        coordinator.ui_access_manager = FakeAccess()
        coordinator._toolbar = FakeToolbar()
        coordinator._tab_widget = FakeTabWidget(index=0)
        coordinator._reset_takeoff_workspace_state = lambda: None
        coordinator._update_export_menu_state = lambda: None
        snapshot = FakeRefreshSnapshot(database_selected=True)
        coordinator._nav = FakeRefreshNav(snapshot)
        coordinator._finish_refresh()
        self.assertEqual(
            coordinator.main_window.project_view.restored_file,
            "active.mdb",
        )

    def test_database_refresh_restores_project_selection_with_file_path(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = FakeUnloadMainWindow()
        coordinator.project_data = FakeUnloadProjectData("active.mdb")
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


if __name__ == "__main__":
    unittest.main()
