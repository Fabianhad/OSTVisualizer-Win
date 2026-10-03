import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PySide6 import QtWidgets
from ost_visualizer.application.dtos.collaboration_dtos import (
    ResourceRef,
    SynchronizationState,
)
from ost_visualizer.application.services.database_capability_service import (
    DatabaseCapabilityService,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.condition_folder import BidConditionFolder
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.components import (
    conditions_sidebar as conditions_sidebar_module,
)
from ost_visualizer.presentation.components.conditions_sidebar import (
    ConditionsSidebar,
)
from ost_visualizer.presentation.components.project_tree_view import _BidTreeWidget
from ost_visualizer.presentation.config import TAB_INDEX_PROJECTS, TAB_INDEX_TAKEOFF
from ost_visualizer.presentation.controllers.menu_controller import MenuController
from ost_visualizer.presentation.coordinators.toolbar_state_coordinator import (
    ToolbarStateCoordinator,
)
from ost_visualizer.presentation.main_window import MainWindow
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

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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

    def test_toolbar_follows_real_sql_capability_service_end_to_end(self):
        # UIAccessManager -> real DatabaseCapabilityService -> real descriptor
        # registry. Only the SQL permission probe is a fake (no server in unit
        # tests); the capability rules themselves are production code.
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_IT_TOOLBAR"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        database_id = descriptor.database_id
        project_data = _permissions__ProjectData()
        project_data.bid_ref = BidRef(database_id, "7")
        ui_state = _permissions__ToolbarUiState(project_data.bid_ref)

        class _SwitchableProbe:
            allowed = False

            def can_edit(self, _database_id):
                return self.allowed

        probe = _SwitchableProbe()
        capabilities = DatabaseCapabilityService(registry, probe)
        manager = self._access_manager(project_data, ui_state, capabilities)
        coordinator = ToolbarStateCoordinator(ui_state, manager, project_data)
        conditions_sidebar = _permissions__FakeConditionsSidebar()
        coordinator.set_conditions_sidebar(conditions_sidebar)
        coordinator.set_plan_view(_permissions__FakePlanView())
        coordinator.set_tab_widget(_permissions__FakeTabWidget(TAB_INDEX_TAKEOFF))

        def create_folder_enabled():
            coordinator.refresh()
            return conditions_sidebar.create_folder_enabled

        # Registered but never connected: no write capability.
        self.assertFalse(create_folder_enabled())
        # Connected without database write permission, even if healthy.
        self.assertFalse(capabilities.mark_connected(database_id))
        capabilities.set_collaboration_state(database_id, SynchronizationState.HEALTHY)
        self.assertFalse(create_folder_enabled())
        # Permission granted but synchronization not healthy yet.
        capabilities.mark_disconnected(database_id)
        probe.allowed = True
        self.assertTrue(capabilities.mark_connected(database_id))
        self.assertFalse(create_folder_enabled())
        # Healthy and permitted: enabled.
        capabilities.set_collaboration_state(database_id, SynchronizationState.HEALTHY)
        self.assertTrue(create_folder_enabled())
        # A lock on this bid's condition collection blocks it; another bid's lock
        # does not.
        capabilities.update_collaboration_resources(
            database_id, frozenset({ResourceRef("conditions_collection", "8", 8)})
        )
        self.assertTrue(create_folder_enabled())
        capabilities.update_collaboration_resources(
            database_id, frozenset({ResourceRef("conditions_collection", "7", 7)})
        )
        self.assertFalse(create_folder_enabled())
        capabilities.update_collaboration_resources(database_id, frozenset())
        self.assertTrue(create_folder_enabled())
        # Losing the connection removes the capability again.
        capabilities.set_collaboration_state(
            database_id, SynchronizationState.DISCONNECTED
        )
        self.assertFalse(create_folder_enabled())

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
        # Positive control: with the bid unlocked the same toolbar enables delete.
        project_data.locked = False
        coordinator.refresh()
        self.assertTrue(delete_action.enabled)

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
        access = _permissions__FakeAccess({Feature.DUPLICATE_BID})
        toolbar = ToolbarStateCoordinator(
            ui_state,
            access,
            SimpleNamespace(
                find_project_uid_for_bid=lambda _ref: None,
                get_hierarchy=lambda: _permissions__hierarchy_with_bids(
                    "bid-1", file_path="C:\\jobs\\test.mdb"
                ),
            ),
        )
        toolbar.set_bid_clipboard(clipboard)
        self.assertTrue(toolbar._can_paste_bid_clipboard())
        # Negative control: the permission, not the path match, gates the paste.
        access.allowed.clear()
        self.assertFalse(toolbar._can_paste_bid_clipboard())
        self.assertTrue(clipboard.has_content())

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


class LockedBidConditionFolderControlsTests(unittest.TestCase):
    """Decision H1: on a status-locked Bid the Condition folder WRITE controls
    (New Folder, Rename/Delete folder, Cut, Paste of a cut, drag-move) follow the real
    UIAccessManager through the real ToolbarStateCoordinator into a real
    ConditionsSidebar, while the read-only and navigation controls (Copy, expand and
    collapse, folder selection) stay enabled. Real: access manager, coordinator,
    sidebar widget, context-menu construction. Fake: project data, UI state, plan view,
    tab widget (permission_support doubles)."""

    @classmethod
    def setUpClass(cls):
        cls._app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _harness(self):
        project_data = _permissions__ProjectData()
        ui_state = _permissions__ToolbarUiState(project_data.bid_ref)
        manager = UIAccessManager(
            _permissions__EventBus(),
            _permissions__License(),
            _permissions__TransactionMonitor(),
            project_data,
            ui_state,
            _permissions__DatabaseCapability(),
        )
        coordinator = ToolbarStateCoordinator(ui_state, manager, project_data)
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        sidebar.load_conditions(
            {
                "c1": Condition(uid="c1", name="First", ref_no=1),
                "c2": Condition(uid="c2", name="Second", ref_no=2),
            },
            {"f1": BidConditionFolder(uid="f1", name="Folder")},
            "Project",
        )
        coordinator.set_conditions_sidebar(sidebar)
        coordinator.set_plan_view(_permissions__FakePlanView())
        coordinator.set_tab_widget(_permissions__FakeTabWidget(TAB_INDEX_TAKEOFF))
        coordinator.refresh()
        return project_data, coordinator, sidebar

    def _context_menu(self, sidebar, item):
        captured = {}

        def capture(menu, _position):
            captured["top"] = {
                action.text(): action.isEnabled()
                for action in menu.actions()
                if action.text()
            }
            captured["new"] = {
                action.text(): action.isEnabled()
                for action in menu.actions()[0].menu().actions()
            }

        with patch.object(sidebar.tree, "itemAt", return_value=item):
            with patch.object(
                conditions_sidebar_module, "exec_transient_menu", capture
            ):
                sidebar._on_context_menu(sidebar.tree.viewport().rect().center())
        return captured

    def _write_signals(self, sidebar):
        emitted = {
            "create_folder": [],
            "rename": [],
            "delete": [],
            "move": [],
            "paste": [],
        }
        sidebar.create_folder_requested.connect(emitted["create_folder"].append)
        sidebar.folder_renamed.connect(lambda *args: emitted["rename"].append(args))
        sidebar.folder_delete_requested.connect(emitted["delete"].append)
        sidebar.condition_folder_move_requested.connect(
            lambda *args: emitted["move"].append(args)
        )
        sidebar.paste_requested.connect(lambda *args: emitted["paste"].append(args))
        return emitted

    def test_unlocked_bid_enables_every_folder_write_control(self):
        # Positive control for the locked test below: same harness, bid unlocked.
        _project_data, _coordinator, sidebar = self._harness()
        emitted = self._write_signals(sidebar)
        folder = sidebar._folder_items["f1"]
        self.assertTrue(sidebar._new_folder_btn.isEnabled())
        sidebar.highlight_conditions({"c1"})
        folder_menu = self._context_menu(sidebar, folder)
        self.assertTrue(folder_menu["new"]["Folder"])
        self.assertTrue(folder_menu["top"]["Rename"])
        self.assertTrue(folder_menu["top"]["Delete"])
        condition_menu = self._context_menu(sidebar, sidebar._condition_items["c1"])
        self.assertTrue(condition_menu["top"]["Cut"])
        self.assertTrue(condition_menu["top"]["Copy"])
        sidebar._cut_selected_conditions()
        self.assertTrue(sidebar._condition_clipboard_cut)
        self.assertTrue(sidebar._can_paste_to_item(folder))
        sidebar._paste_copied_conditions(folder)
        sidebar._on_condition_folder_move("c1", "f1")
        sidebar._on_new_folder_clicked()
        self.assertEqual(len(emitted["paste"]), 1)
        self.assertTrue(emitted["paste"][0][1]["cut"])
        self.assertEqual(emitted["move"], [("c1", "f1")])
        self.assertEqual(emitted["create_folder"], [""])

    def test_locked_bid_disables_every_folder_write_control(self):
        project_data, coordinator, sidebar = self._harness()
        emitted = self._write_signals(sidebar)
        folder = sidebar._folder_items["f1"]
        sidebar.highlight_conditions({"c1"})
        sidebar._cut_selected_conditions()
        self.assertTrue(sidebar._can_paste_to_item(folder))
        sidebar.tree.clearSelection()
        project_data.locked = True
        coordinator.refresh()
        self.assertFalse(sidebar._new_folder_btn.isEnabled())
        sidebar._on_new_folder_clicked()
        folder_menu = self._context_menu(sidebar, folder)
        self.assertFalse(folder_menu["new"]["Folder"])
        self.assertFalse(folder_menu["top"]["Rename"])
        self.assertFalse(folder_menu["top"]["Delete"])
        self.assertFalse(sidebar._delete_btn.isEnabled())
        sidebar._request_folder_delete()
        sidebar._request_create_in_context(folder, folder=True)
        # A cut staged before the lock cannot be pasted any more.
        self.assertTrue(sidebar._condition_clipboard_cut)
        self.assertFalse(sidebar._can_paste_to_item(folder))
        sidebar._paste_copied_conditions(folder)
        sidebar.highlight_conditions({"c2"})
        self.assertFalse(sidebar._can_cut_selected_conditions())
        condition_menu = self._context_menu(sidebar, sidebar._condition_items["c2"])
        self.assertFalse(condition_menu["top"]["Cut"])
        sidebar._cut_selected_conditions()
        self.assertEqual(sidebar._copied_condition_uids, ["c1"])
        sidebar._on_condition_folder_move("c2", "f1")
        sidebar.start_folder_edit("f1")
        self.assertIsNone(sidebar._editing_folder)
        self.assertEqual(
            emitted,
            {"create_folder": [], "rename": [], "delete": [], "move": [], "paste": []},
        )

    def test_locked_bid_keeps_copy_and_navigation_controls_enabled(self):
        project_data, coordinator, sidebar = self._harness()
        project_data.locked = True
        coordinator.refresh()
        sidebar.highlight_conditions({"c1"})
        self.assertTrue(sidebar._can_copy_selected_conditions())
        condition_menu = self._context_menu(sidebar, sidebar._condition_items["c1"])
        self.assertTrue(condition_menu["top"]["Copy"])
        for navigation in (
            "Expand All Types",
            "Collapse All Types",
            "Expand All Folders",
        ):
            self.assertTrue(condition_menu["top"][navigation], navigation)
        sidebar._copy_selected_conditions()
        self.assertEqual(sidebar._copied_condition_uids, ["c1"])
        self.assertFalse(sidebar._condition_clipboard_cut)
        sidebar.collapse_all_types()
        sidebar.expand_all_types()
        sidebar.expand_all_folders()
        folder = sidebar._folder_items["f1"]
        sidebar.tree.clearSelection()
        sidebar.tree.setCurrentItem(folder)
        folder.setSelected(True)
        self.assertEqual(sidebar._selected_folder_uids, ["f1"])


class LockedBidProjectTreeControlsTests(unittest.TestCase):
    """Decision P4: a status-locked Bid protects its own contents, not where it sits in
    the project tree. With the active Bid locked, the project-level structure controls
    (New Project/Folder menu items, project delete toolbar action, Bid drag-move and
    restore of OTHER Bids) stay enabled while the Bid-contents permissions are denied.
    Decision Q1 narrows that for the ACTIVE locked Bid itself: its drag-move, restore,
    cut and trash controls are disabled (the services refuse them) while a non-active
    Bid stays movable. Real: UIAccessManager, ToolbarStateCoordinator, MenuController
    gate, _BidTreeWidget, MainWindow command gates. Fake: project data, UI state, tab
    widget, plan view."""

    @classmethod
    def setUpClass(cls):
        cls._app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _manager(self, locked, editable=True):
        project_data = _ProjectTreeData()
        project_data.locked = locked
        ui_state = _ProjectSelectionUiState(project_data.bid_ref)
        manager = UIAccessManager(
            _permissions__EventBus(),
            _permissions__License(),
            _permissions__TransactionMonitor(),
            project_data,
            ui_state,
            _permissions__DatabaseCapability(editable=editable),
        )
        return project_data, ui_state, manager

    def _controls(self, locked, editable=True):
        project_data, ui_state, manager = self._manager(locked, editable)
        coordinator = ToolbarStateCoordinator(ui_state, manager, project_data)
        delete_action = _permissions__FakeAction()
        coordinator.set_delete_action(delete_action)
        coordinator.set_plan_view(_permissions__FakePlanView())
        coordinator.set_tab_widget(_permissions__FakeTabWidget(TAB_INDEX_PROJECTS))
        coordinator.refresh()
        menu = MenuController.__new__(MenuController)
        menu.window = SimpleNamespace(is_summary_tab_active=lambda: False)
        menu.ui_state_manager = ui_state
        menu.ui_access_manager = manager
        tree = _BidTreeWidget()
        self.addCleanup(tree.deleteLater)
        tree.set_ui_access_manager(manager)
        item = QtWidgets.QTreeWidgetItem(["Bid"])
        item.setData(
            0,
            tree._ITEM_ROLE,
            ("bid", project_data.bid_ref.bid_uid, "C:/jobs/test.mdb"),
        )
        tree.addTopLevelItem(item)
        other_item = QtWidgets.QTreeWidgetItem(["Other Bid"])
        other_item.setData(0, tree._ITEM_ROLE, ("bid", "8", "C:/jobs/test.mdb"))
        tree.addTopLevelItem(other_item)
        tree._drag_items = [other_item]
        drag_other = tree._move_bids_allowed()
        tree._drag_items = [item]
        calls = []
        window = MainWindow.__new__(MainWindow)
        window.ui_access_manager = manager
        window.handlers = SimpleNamespace(
            delete=SimpleNamespace(
                restore_bids=lambda refs: calls.append(("restore", refs)),
                move_bids=lambda refs, target: calls.append(("move", refs, target)),
            )
        )
        return {
            "manager": manager,
            "delete_action": delete_action,
            "create_items": menu._should_enable_project_tree_creation(),
            "drag": tree._move_bids_allowed(),
            "drag_other": drag_other,
            "window": window,
            "calls": calls,
            "bid_ref": project_data.bid_ref,
            "other_ref": BidRef("C:/jobs/test.mdb", "8"),
        }

    def _bid_toolbar_actions(self, locked, selected_bid_uid):
        project_data = _ProjectTreeData()
        project_data.locked = locked
        selected = BidRef("C:/jobs/test.mdb", selected_bid_uid)
        ui_state = _permissions__ToolbarUiState(selected)
        manager = UIAccessManager(
            _permissions__EventBus(),
            _permissions__License(),
            _permissions__TransactionMonitor(),
            project_data,
            ui_state,
            _permissions__DatabaseCapability(),
        )
        coordinator = ToolbarStateCoordinator(ui_state, manager, project_data)
        trash_action = _permissions__FakeAction()
        cut_action = _permissions__FakeAction()
        coordinator.set_delete_action(trash_action)
        coordinator.set_cut_action(cut_action)
        coordinator.set_plan_view(_permissions__FakePlanView())
        coordinator.set_tab_widget(_permissions__FakeTabWidget(TAB_INDEX_PROJECTS))
        coordinator.refresh()
        return trash_action.enabled, cut_action.enabled

    def test_locked_bid_keeps_project_tree_structure_controls_enabled(self):
        controls = self._controls(locked=True)
        manager = controls["manager"]
        # The Bid-contents permissions really are denied in this harness.
        self.assertFalse(manager.is_allowed(Feature.EDIT_CONDITION_STRUCTURE))
        self.assertFalse(manager.is_allowed(Feature.EDIT_CONDITION))
        self.assertFalse(
            manager.get_plan_surface_access(
                manager.current_plan_surface_context()
            ).can_edit_plan_items
        )
        # The project-level controls are not.
        self.assertTrue(controls["delete_action"].enabled)
        self.assertTrue(controls["create_items"])
        # Decision Q1: a NON-active Bid stays movable/restorable on a locked Bid ...
        self.assertTrue(controls["drag_other"])
        window, bid_ref = controls["window"], controls["bid_ref"]
        other_ref = controls["other_ref"]
        MainWindow._restore_project_bids(window, [other_ref])
        MainWindow._move_project_bids(window, [other_ref], "project-2")
        self.assertEqual(
            controls["calls"],
            [("restore", [other_ref]), ("move", [other_ref], "project-2")],
        )
        # ... but the ACTIVE locked Bid itself is not: drag, restore, move, trash, cut.
        self.assertFalse(controls["drag"])
        controls["calls"].clear()
        MainWindow._restore_project_bids(window, [bid_ref])
        MainWindow._move_project_bids(window, [bid_ref], "project-2")
        self.assertEqual(controls["calls"], [])
        self.assertEqual(self._bid_toolbar_actions(True, "7"), (False, False))
        self.assertEqual(self._bid_toolbar_actions(True, "8"), (True, True))
        self.assertEqual(self._bid_toolbar_actions(False, "7"), (True, True))

    def test_project_tree_structure_controls_follow_role_not_lock(self):
        # Unlocked editor is the positive control; the viewer is denied in both lock
        # states, so the enabled locked-editor controls above are not vacuous.
        for editable, locked in ((True, False), (False, False), (False, True)):
            with self.subTest(editable=editable, locked=locked):
                controls = self._controls(locked=locked, editable=editable)
                self.assertEqual(controls["delete_action"].enabled, editable)
                self.assertEqual(controls["create_items"], editable)
                self.assertEqual(controls["drag"], editable)
                self.assertEqual(controls["drag_other"], editable)
                MainWindow._restore_project_bids(
                    controls["window"], [controls["bid_ref"]]
                )
                MainWindow._move_project_bids(
                    controls["window"], [controls["bid_ref"]], "project-2"
                )
                self.assertEqual(
                    [call[0] for call in controls["calls"]],
                    ["restore", "move"] if editable else [],
                )


class _ProjectTreeData(_permissions__ProjectData):
    def project_has_bids(self, _project_uid, _file_path):
        return False


class _ProjectSelectionUiState(_permissions__ToolbarUiState):
    """Project-tree selection: one empty project selected, no Bid refs."""

    selected_project_uids = ["2"]
    selected_project_file_path = "C:/jobs/test.mdb"

    def get_selected_bid_refs(self):
        return []
