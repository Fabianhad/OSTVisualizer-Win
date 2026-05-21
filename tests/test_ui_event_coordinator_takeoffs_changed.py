import unittest
from ost_visualizer.domain.entities.hierarchy_data import HierarchyData
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
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

    def refresh(self):
        self.refreshes += 1


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

    def force_exit(self):
        self.force_exit_count += 1


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


class UIEventCoordinatorTakeoffsChangedTests(unittest.TestCase):
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
        coordinator._nav = type(
            "FakeNav",
            (),
            {"transition_to": lambda self, state: setattr(self, "state", state)},
        )()
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
        snapshot = type(
            "Snapshot",
            (),
            {
                "bid_ref": None,
                "project_uid": None,
                "database_selected": True,
                "selected_file_path": "active.mdb",
            },
        )()
        coordinator._nav = type(
            "FakeNav",
            (),
            {
                "refresh_snapshot": snapshot,
                "finish_refresh": lambda self, state: setattr(self, "state", state),
            },
        )()
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
        snapshot = type(
            "Snapshot",
            (),
            {
                "bid_ref": None,
                "project_uid": "project-1",
                "selected_file_path": "active.mdb",
            },
        )()
        coordinator._nav = type(
            "FakeNav",
            (),
            {
                "refresh_snapshot": snapshot,
                "finish_refresh": lambda self, state: setattr(self, "state", state),
            },
        )()
        coordinator._finish_refresh()
        self.assertEqual(
            coordinator.main_window.project_view.restored_project,
            ("project-1", "active.mdb"),
        )


if __name__ == "__main__":
    unittest.main()
