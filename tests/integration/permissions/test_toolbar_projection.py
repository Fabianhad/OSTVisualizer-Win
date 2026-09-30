import unittest
from types import SimpleNamespace
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from ost_visualizer.presentation.coordinators.toolbar_state_coordinator import (
    ToolbarStateCoordinator,
)
from ost_visualizer.presentation.managers.ui_access_manager import (
    _DATABASE_EDIT_FEATURES,
    MAIN_PLAN_SURFACE_ID,
    Feature,
    UIAccessManager,
)
from ost_visualizer.presentation.services.bid_clipboard_service import (
    BidClipboardService,
)
from tests.application.services.write_permission_support import (
    _DatabaseCapability as _permissions__DatabaseCapability,
    _EventBus as _permissions__EventBus,
    _ProjectData as _permissions__ProjectData,
    _TransactionMonitor as _permissions__TransactionMonitor,
    _hierarchy_with_bids as _permissions__hierarchy_with_bids,
)
from tests.presentation.managers.permission_support import (
    _FakeAccess as _permissions__FakeAccess,
    _FakeAction as _permissions__FakeAction,
    _FakeConditionsSidebar as _permissions__FakeConditionsSidebar,
    _FakePlanView as _permissions__FakePlanView,
    _FakeTabWidget as _permissions__FakeTabWidget,
    _License as _permissions__License,
    _ToolbarUiState as _permissions__ToolbarUiState,
    _UiState as _permissions__UiState,
)


class BidLockPermissionTests(unittest.TestCase):
    def _access_manager(self, project_data, ui_state=None, capability=None):
        return UIAccessManager(
            _permissions__EventBus(),
            _permissions__License(),
            _permissions__TransactionMonitor(),
            project_data,
            ui_state or _permissions__UiState(project_data.bid_ref),
            capability or _permissions__DatabaseCapability(),
        )

    def test_toolbar_revokes_active_inline_text_editing_with_database_access(self):
        project_data = _permissions__ProjectData()
        ui_state = _permissions__ToolbarUiState(project_data.bid_ref)
        capability = _permissions__DatabaseCapability(editable=True)
        manager = self._access_manager(project_data, ui_state, capability)
        plan_view = _permissions__FakePlanView()
        coordinator = ToolbarStateCoordinator(ui_state, manager, project_data)
        coordinator.set_plan_view(plan_view)
        coordinator.set_tab_widget(_permissions__FakeTabWidget(TAB_INDEX_TAKEOFF))
        coordinator.refresh()
        capability.editable = False
        coordinator.refresh()
        self.assertEqual(plan_view.inline_edit_enabled, [True, False])

    def test_condition_folder_toolbar_uses_condition_structure_permission(self):
        project_data = _permissions__ProjectData()
        ui_state = _permissions__ToolbarUiState(project_data.bid_ref)
        manager = self._access_manager(project_data, ui_state)
        coordinator = ToolbarStateCoordinator(ui_state, manager, project_data)
        conditions_sidebar = _permissions__FakeConditionsSidebar()
        coordinator.set_conditions_sidebar(conditions_sidebar)
        coordinator.set_plan_view(_permissions__FakePlanView())
        coordinator.set_tab_widget(_permissions__FakeTabWidget(TAB_INDEX_TAKEOFF))
        coordinator.refresh()
        self.assertTrue(conditions_sidebar.create_folder_enabled)
        manager.set_text_annotation_edit_active(True, surface_id=MAIN_PLAN_SURFACE_ID)
        coordinator.refresh()
        self.assertFalse(conditions_sidebar.create_folder_enabled)

    def test_takeoff_tab_delete_toolbar_uses_plan_item_selection_permission(self):
        project_data = _permissions__ProjectData()
        project_data.locked = True
        ui_state = _permissions__ToolbarUiState(project_data.bid_ref)
        manager = self._access_manager(project_data, ui_state)
        coordinator = ToolbarStateCoordinator(ui_state, manager, project_data)
        delete_action = _permissions__FakeAction()
        coordinator.set_delete_action(delete_action)
        coordinator.set_plan_view(_permissions__FakePlanView())
        coordinator.set_tab_widget(_permissions__FakeTabWidget(TAB_INDEX_TAKEOFF))
        coordinator.refresh()
        self.assertFalse(delete_action.enabled)

    def test_annotation_toolbar_uses_place_annotations_permission(self):
        project_data = _permissions__ProjectData()
        ui_state = _permissions__ToolbarUiState(project_data.bid_ref)
        manager = self._access_manager(project_data, ui_state)
        coordinator = ToolbarStateCoordinator(ui_state, manager, project_data)
        dimension_action = _permissions__FakeAction()
        line_action = _permissions__FakeAction()
        cloud_action = _permissions__FakeAction()
        plan_view = _permissions__FakePlanView()
        coordinator.set_annotation_tool_actions(
            [dimension_action, line_action, cloud_action]
        )
        coordinator.set_plan_view(plan_view)
        coordinator.set_tab_widget(_permissions__FakeTabWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_view_stack(_permissions__FakeTabWidget(1))
        coordinator.refresh()
        self.assertTrue(dimension_action.enabled)
        self.assertTrue(line_action.enabled)
        self.assertTrue(cloud_action.enabled)
        project_data.annotation_layer_visible = False
        coordinator.refresh()
        self.assertFalse(dimension_action.enabled)
        self.assertFalse(line_action.enabled)
        self.assertFalse(cloud_action.enabled)
        self.assertTrue(manager.is_allowed(Feature.PLACE_PLAN_ITEMS))
        self.assertFalse(manager.is_allowed(Feature.PLACE_ANNOTATIONS))
        project_data.annotation_layer_visible = True
        coordinator.refresh()
        self.assertTrue(dimension_action.enabled)
        self.assertTrue(line_action.enabled)
        self.assertTrue(cloud_action.enabled)
        project_data.locked = True
        coordinator.refresh()
        self.assertFalse(dimension_action.enabled)
        self.assertFalse(line_action.enabled)
        self.assertFalse(cloud_action.enabled)
        project_data.locked = False
        manager.set_text_annotation_edit_active(True, surface_id=MAIN_PLAN_SURFACE_ID)
        coordinator.refresh()
        self.assertFalse(dimension_action.enabled)
        self.assertFalse(line_action.enabled)
        self.assertFalse(cloud_action.enabled)
        manager.set_text_annotation_edit_active(False, surface_id=MAIN_PLAN_SURFACE_ID)
        plan_view.current_page_uid = None
        coordinator.refresh()
        self.assertFalse(dimension_action.enabled)
        self.assertFalse(line_action.enabled)
        self.assertFalse(cloud_action.enabled)
        plan_view.current_page_uid = "page-1"
        coordinator.refresh()
        self.assertTrue(dimension_action.enabled)
        self.assertTrue(line_action.enabled)
        self.assertTrue(cloud_action.enabled)

    def test_toolbar_paste_allows_same_database_with_normalized_paths(self):
        clipboard = BidClipboardService()
        clipboard.copy([BidRef("C:/jobs/test.mdb", "bid-1")])
        ui_state = SimpleNamespace(
            selected_file_path="C:\\jobs\\test.mdb",
            selected_project_uid="project-2",
            selected_project_uids=["project-2"],
            selected_project_file_path="C:\\jobs\\test.mdb",
            get_selected_bid_ref=lambda: None,
            get_selected_bid_refs=lambda: [],
        )
        toolbar = ToolbarStateCoordinator(
            ui_state,
            _permissions__FakeAccess({Feature.DUPLICATE_BID}),
            SimpleNamespace(
                find_project_uid_for_bid=lambda _ref: None,
                get_hierarchy=lambda: _permissions__hierarchy_with_bids(
                    "bid-1", file_path="C:\\jobs\\test.mdb"
                ),
            ),
        )
        toolbar.set_bid_clipboard(clipboard)
        self.assertTrue(toolbar._can_paste_bid_clipboard())

    def test_toolbar_prunes_remotely_deleted_bid_clipboard_sources(self):
        clipboard = BidClipboardService()
        clipboard.cut([BidRef("C:/jobs/test.mdb", "deleted-bid")])
        ui_state = SimpleNamespace(
            selected_file_path="C:/jobs/test.mdb",
            selected_project_uid="project-2",
            selected_project_uids=["project-2"],
            selected_project_file_path="C:/jobs/test.mdb",
            get_selected_bid_ref=lambda: None,
            get_selected_bid_refs=lambda: [],
        )
        toolbar = ToolbarStateCoordinator(
            ui_state,
            _permissions__FakeAccess({Feature.DELETE_BID}),
            SimpleNamespace(
                get_hierarchy=lambda: _permissions__hierarchy_with_bids(),
                find_project_uid_for_bid=lambda _ref: None,
            ),
        )
        toolbar.set_bid_clipboard(clipboard)
        self.assertFalse(toolbar._can_paste_bid_clipboard())
        self.assertFalse(clipboard.has_content())
        self.assertFalse(clipboard.is_cut)

    def test_toolbar_prunes_clipboard_source_moved_to_deleted_bids(self):
        clipboard = BidClipboardService()
        clipboard.copy([BidRef("C:/jobs/test.mdb", "bid-1")])
        hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path="C:/jobs/test.mdb",
                    bid_projects={
                        "1": HierarchyProjectInfo(
                            name="Deleted Bids",
                            bids=[HierarchyBidInfo(uid="bid-1")],
                        )
                    },
                )
            ]
        )
        ui_state = SimpleNamespace(
            selected_file_path="C:/jobs/test.mdb",
            selected_project_uid="project-2",
            selected_project_uids=["project-2"],
            selected_project_file_path="C:/jobs/test.mdb",
            get_selected_bid_ref=lambda: None,
            get_selected_bid_refs=lambda: [],
        )
        toolbar = ToolbarStateCoordinator(
            ui_state,
            _permissions__FakeAccess({Feature.DUPLICATE_BID}),
            SimpleNamespace(
                get_hierarchy=lambda: hierarchy,
                find_project_uid_for_bid=lambda _ref: None,
            ),
        )
        toolbar.set_bid_clipboard(clipboard)
        self.assertFalse(toolbar._can_paste_bid_clipboard())
        self.assertFalse(clipboard.has_content())

    def test_toolbar_paste_allowed_when_project_target_replaces_bid_selection(self):
        clipboard = BidClipboardService()
        clipboard.copy([BidRef("C:/jobs/test.mdb", "7")])
        project_data = _permissions__ProjectData()
        ui_state = SimpleNamespace(
            selected_file_path="C:/jobs/test.mdb",
            selected_project_uid="project-2",
            selected_project_uids=["project-2"],
            selected_project_file_path="C:/jobs/test.mdb",
            place_condition_uid=None,
            get_selected_bid_ref=lambda: None,
            get_selected_bid_refs=lambda: [],
            is_database_selected=lambda: False,
        )
        manager = self._access_manager(project_data, ui_state)
        self.assertFalse(manager.is_allowed(Feature.DUPLICATE_BID))
        toolbar = ToolbarStateCoordinator(ui_state, manager, project_data)
        toolbar.set_bid_clipboard(clipboard)
        self.assertTrue(toolbar._can_paste_bid_clipboard())
