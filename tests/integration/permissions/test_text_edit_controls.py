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
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.managers.ui_access_manager import (
    _DATABASE_EDIT_FEATURES,
    MAIN_PLAN_SURFACE_ID,
    Feature,
    UIAccessManager,
)
from tests.application.services.write_permission_support import (
    _DatabaseCapability as _permissions__DatabaseCapability,
    _EventBus as _permissions__EventBus,
    _ProjectData as _permissions__ProjectData,
    _TransactionMonitor as _permissions__TransactionMonitor,
    _hierarchy_with_bids as _permissions__hierarchy_with_bids,
)
from tests.presentation.managers.permission_support import (
    _FakeAction as _permissions__FakeAction,
    _FakeLayersSidebar as _permissions__FakeLayersSidebar,
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

    def test_exiting_text_edit_reenables_shell_controls_without_page_switch(self):
        project_data = _permissions__ProjectData()
        ui_state = _permissions__ToolbarUiState(project_data.bid_ref)
        manager = self._access_manager(project_data, ui_state)
        toolbar = ToolbarStateCoordinator(ui_state, manager, project_data)
        cover_sheet_button = _permissions__FakeAction()
        layers_sidebar = _permissions__FakeLayersSidebar()
        toolbar.set_cover_sheet_button(cover_sheet_button)
        toolbar.set_bid_layers_sidebar(layers_sidebar)
        toolbar.set_plan_view(_permissions__FakePlanView())
        toolbar.set_tab_widget(_permissions__FakeTabWidget(TAB_INDEX_TAKEOFF))
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_access_manager = manager
        coordinator._update_menu_state = lambda: None
        coordinator._on_text_annotation_edit_mode_changed(True)
        self.assertFalse(manager.is_allowed(Feature.COVER_SHEET))
        self.assertFalse(cover_sheet_button.enabled)
        self.assertFalse(layers_sidebar.interactive)
        coordinator._on_text_annotation_edit_mode_changed(False)
        self.assertTrue(manager.is_allowed(Feature.COVER_SHEET))
        self.assertTrue(cover_sheet_button.enabled)
        self.assertTrue(layers_sidebar.interactive)
