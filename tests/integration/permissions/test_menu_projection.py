import unittest
from types import SimpleNamespace
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.controllers.menu_controller import MenuController
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
    _License as _permissions__License,
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

    def test_shared_menu_annotation_tools_use_place_annotations_permission(self):
        project_data = _permissions__ProjectData()
        manager = self._access_manager(project_data)
        dimension_action = _permissions__FakeAction()
        dimension_action.enabled = True
        place_action = _permissions__FakeAction()
        place_action.enabled = True
        controller = MenuController.__new__(MenuController)
        controller._actions = {
            "dimension_tool": dimension_action,
            "place_tool": place_action,
        }
        controller.update_menu_states = lambda: None
        controller.ui_access_manager = manager
        project_data.annotation_layer_visible = False
        self.assertFalse(controller.is_context_command_enabled("dimension_tool"))
        self.assertTrue(controller.is_context_command_enabled("place_tool"))
        self.assertTrue(dimension_action.enabled)
        project_data.annotation_layer_visible = True
        self.assertTrue(controller.is_context_command_enabled("dimension_tool"))
        self.assertTrue(controller.is_context_command_enabled("place_tool"))
