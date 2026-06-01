import logging
import unittest
from types import SimpleNamespace
from ost_visualizer.application.dtos.update_condition_dto import UpdateConditionDto
from ost_visualizer.application.services.active_bid_write_guard import (
    ActiveBidWriteGuard,
)
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
    WriteReloadResult,
)
from ost_visualizer.domain.entities.area import BidArea, BidAreaChangeset
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from ost_visualizer.presentation.controllers.menu_controller import MenuController
from ost_visualizer.presentation.coordinators.toolbar_state_coordinator import (
    ToolbarStateCoordinator,
)
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.handlers.condition_action_handler import (
    ConditionActionHandler,
)
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.managers.ui_access_manager import (
    Feature,
    UIAccessManager,
)


class _EventBus:
    def __init__(self):
        self.subscriptions = []

    def subscribe(self, event_type, callback):
        self.subscriptions.append((event_type, callback))

    def unsubscribe(self, event_type, callback):
        self.subscriptions.remove((event_type, callback))

    def publish(self, event_type, **kwargs):
        pass


class _License:
    def has_valid_license(self):
        return True


class _TransactionMonitor:
    def is_ost_active(self):
        return False


class _ProjectData:
    def __init__(self):
        self.locked = False
        self.bid_ref = BidRef(file_path="C:/jobs/test.mdb", bid_uid="7")
        self.project_uid = "project-1"

    def is_current_bid_locked(self):
        return self.locked

    def get_current_bid_ref(self):
        return self.bid_ref

    def find_project_uid_for_bid(self, bid_ref):
        if bid_ref == self.bid_ref:
            return self.project_uid
        return None


class _UiState:
    def __init__(self, bid_ref):
        self._bid_ref = bid_ref
        self.selected_file_path = bid_ref.file_path
        self.selected_project_uid = None
        self.place_condition_uid = None

    def get_selected_bid_ref(self):
        return self._bid_ref

    def is_database_selected(self):
        return True


class _ToolbarUiState(_UiState):
    selected_project_uid = None
    selected_project_uids = []

    def get_selected_bid_refs(self):
        return [self._bid_ref] if self._bid_ref else []


class _FakeAction:
    def __init__(self):
        self.enabled = None
        self.checked = False

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)

    def isChecked(self):
        return self.checked


class _FakeLayersSidebar:
    def __init__(self):
        self.interactive = None

    def set_interactive(self, interactive):
        self.interactive = bool(interactive)


class _FakeConditionsSidebar:
    def __init__(self):
        self.create_folder_enabled = None

    def get_selected_condition_uids(self):
        return []

    def is_condition_placeable(self, _uid):
        return False

    def set_create_enabled(self, _enabled):
        pass

    def set_duplicate_enabled(self, _enabled):
        pass

    def set_delete_enabled(self, _enabled):
        pass

    def set_edit_enabled(self, _enabled, read_only_enabled=False):
        pass

    def set_create_folder_enabled(self, enabled):
        self.create_folder_enabled = bool(enabled)


class _FakeTabWidget:
    def __init__(self, index):
        self._index = index

    def currentIndex(self):
        return self._index


class _FakePlanView:
    has_selection = True
    place_condition_uid = None
    current_page_uid = "page-1"

    def __init__(self):
        self.deleted = 0
        self.selected_all = 0

    def selected_takeoff_condition_uid(self):
        return None

    def set_selection_enabled(self, _enabled):
        pass

    def delete_selected(self):
        self.deleted += 1

    def select_all(self):
        self.selected_all += 1

    def is_text_annotation_inline_edit_active(self):
        return False


class _UseCase:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def execute(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


class _SequenceUseCase:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def execute(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.results:
            return self.results.pop(0)
        return False


class _ForbiddenUseCase:
    def execute(self, *args, **kwargs):
        raise AssertionError("locked bid guard did not block the write")


class _FakeAccess:
    def __init__(self, allowed):
        self.allowed = set(allowed)
        self.checked = []

    def is_allowed(self, feature):
        self.checked.append(feature)
        return feature in self.allowed


class _ConditionStructureWriteService:
    def __init__(self):
        self.deleted_folders = []
        self.condition_updates = []
        self.condition_update_kwargs = []
        self.reloads = []

    def delete_condition_folders(self, file_path, folder_uids):
        self.deleted_folders.append((file_path, list(folder_uids)))
        return True

    def update_condition(self, file_path, bid_uid, condition_uid, dto, **kwargs):
        self.condition_updates.append((file_path, bid_uid, condition_uid, dto))
        self.condition_update_kwargs.append(dict(kwargs))
        return SimpleNamespace(success=True)

    def reload_and_notify(self, file_path):
        self.reloads.append(file_path)
        return True


def _write_service(project_data, reload_success=True):
    logger = logging.getLogger(__name__ + ".write_service")
    logger.propagate = False
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    forbidden = _ForbiddenUseCase()
    delete_bids = _UseCase(True)
    duplicate_bid = _UseCase("new-bid")
    update_bid_job_status = _UseCase(True)
    service = ProjectWriteService(
        delete_bids=delete_bids,
        delete_projects=forbidden,
        create_project=forbidden,
        rename_project=forbidden,
        move_bids=forbidden,
        duplicate_bid=duplicate_bid,
        create_bid=forbidden,
        delete_conditions=forbidden,
        duplicate_conditions=forbidden,
        update_condition=forbidden,
        renumber_conditions=forbidden,
        insert_condition=forbidden,
        insert_condition_folder=forbidden,
        rename_condition_folder=forbidden,
        delete_condition_folders=forbidden,
        save_takeoff_positions=forbidden,
        save_takeoff_rotations=forbidden,
        save_takeoff_text_properties=forbidden,
        save_takeoffs_area=forbidden,
        save_takeoffs_condition=forbidden,
        set_takeoffs_negative=forbidden,
        set_takeoff_curve=forbidden,
        insert_takeoffs=forbidden,
        delete_takeoffs=forbidden,
        delete_pages=forbidden,
        save_cover_sheet=forbidden,
        update_bid_job_status=update_bid_job_status,
        save_job_statuses=forbidden,
        save_bid_areas=forbidden,
        save_page_name=forbidden,
        save_page_scale=forbidden,
        save_page_show_mode=forbidden,
        save_page_overlay_image=forbidden,
        save_page_invert=forbidden,
        save_page_bitonal=forbidden,
        save_page_image_adjustments=forbidden,
        save_page_area=forbidden,
        save_employees=forbidden,
        save_pay_classes=forbidden,
        save_condition_types=forbidden,
        update_layer_show=forbidden,
        update_all_layers_show=forbidden,
        update_layer_name=forbidden,
        insert_layer=forbidden,
        delete_layer=forbidden,
        swap_layer_sequence=forbidden,
        save_bid_selected_page=forbidden,
        save_page_view_state=forbidden,
        reload_database=lambda _file_path: reload_success,
        event_bus=_EventBus(),
        logger=logger,
        bid_write_guard=ActiveBidWriteGuard(project_data, logger),
    )
    return service, update_bid_job_status, delete_bids, duplicate_bid


class BidLockPermissionTests(unittest.TestCase):
    def _access_manager(self, project_data, ui_state=None):
        return UIAccessManager(
            _EventBus(),
            _License(),
            _TransactionMonitor(),
            project_data,
            ui_state or _UiState(project_data.bid_ref),
        )

    def test_bid_lock_applies_and_unlocks_immediately_in_access_manager(self):
        project_data = _ProjectData()
        manager = self._access_manager(project_data)
        self.assertTrue(manager.is_allowed(Feature.EDIT_PROJECT_TREE_STRUCTURE))
        self.assertTrue(manager.is_allowed(Feature.EDIT_CONDITION_STRUCTURE))
        self.assertTrue(manager.is_allowed(Feature.EDIT_CONDITION))
        self.assertTrue(manager.is_allowed(Feature.SELECT_PLAN_ITEMS))
        self.assertTrue(manager.is_allowed(Feature.PLACE_PLAN_ITEMS))
        self.assertTrue(manager.is_allowed(Feature.EDIT_ANNOTATION_TEXT))
        project_data.locked = True
        self.assertTrue(manager.is_allowed(Feature.EDIT_PROJECT_TREE_STRUCTURE))
        self.assertTrue(manager.is_allowed(Feature.EDIT_CONDITION_STRUCTURE))
        self.assertFalse(manager.is_allowed(Feature.EDIT_CONDITION))
        self.assertFalse(manager.is_allowed(Feature.SELECT_PLAN_ITEMS))
        self.assertFalse(manager.is_allowed(Feature.PLACE_PLAN_ITEMS))
        self.assertFalse(manager.is_allowed(Feature.EDIT_ANNOTATION_TEXT))
        self.assertTrue(manager.is_allowed(Feature.DELETE_BID))
        self.assertTrue(manager.is_allowed(Feature.DUPLICATE_BID))
        self.assertTrue(manager.is_allowed(Feature.EDIT_BID_JOB_STATUS))
        project_data.locked = False
        self.assertTrue(manager.is_allowed(Feature.EDIT_PROJECT_TREE_STRUCTURE))
        self.assertTrue(manager.is_allowed(Feature.EDIT_CONDITION_STRUCTURE))
        self.assertTrue(manager.is_allowed(Feature.EDIT_CONDITION))
        self.assertTrue(manager.is_allowed(Feature.SELECT_PLAN_ITEMS))
        self.assertTrue(manager.is_allowed(Feature.PLACE_PLAN_ITEMS))
        self.assertTrue(manager.is_allowed(Feature.DELETE_BID))
        self.assertTrue(manager.is_allowed(Feature.DUPLICATE_BID))

    def test_split_structure_permissions_keep_existing_blockers(self):
        project_data = _ProjectData()
        manager = self._access_manager(project_data)
        self.assertTrue(manager.can_create_project_tree_items(True))
        self.assertFalse(manager.can_create_project_tree_items(False))
        self.assertTrue(manager.is_allowed(Feature.EDIT_PROJECT_TREE_STRUCTURE))
        self.assertTrue(manager.is_allowed(Feature.EDIT_CONDITION_STRUCTURE))
        manager.set_area_placement_active(True)
        self.assertFalse(manager.can_create_project_tree_items(True))
        self.assertFalse(manager.is_allowed(Feature.EDIT_PROJECT_TREE_STRUCTURE))
        self.assertFalse(manager.is_allowed(Feature.EDIT_CONDITION_STRUCTURE))
        manager.set_area_placement_active(False)
        manager.set_text_annotation_edit_active(True)
        self.assertFalse(manager.can_create_project_tree_items(True))
        self.assertFalse(manager.is_allowed(Feature.EDIT_PROJECT_TREE_STRUCTURE))
        self.assertFalse(manager.is_allowed(Feature.EDIT_CONDITION_STRUCTURE))

    def test_condition_folder_toolbar_uses_condition_structure_permission(self):
        project_data = _ProjectData()
        ui_state = _ToolbarUiState(project_data.bid_ref)
        manager = self._access_manager(project_data, ui_state)
        coordinator = ToolbarStateCoordinator(ui_state, manager, project_data)
        conditions_sidebar = _FakeConditionsSidebar()
        coordinator.set_conditions_sidebar(conditions_sidebar)
        coordinator.set_plan_view(_FakePlanView())
        coordinator.set_tab_widget(_FakeTabWidget(TAB_INDEX_TAKEOFF))
        coordinator.refresh()
        self.assertTrue(conditions_sidebar.create_folder_enabled)
        manager.set_text_annotation_edit_active(True)
        coordinator.refresh()
        self.assertFalse(conditions_sidebar.create_folder_enabled)

    def _condition_structure_handler(self, allowed):
        access = _FakeAccess(allowed)
        write_service = _ConditionStructureWriteService()
        coordinator = SimpleNamespace(
            ui_access_manager=access,
            conditions_sidebar=None,
        )
        ui_state = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("db.mdb", "bid-1")
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=write_service,
            project_read_service=None,
            project_data=SimpleNamespace(),
            ui_state_manager=ui_state,
        )
        return handler, access, write_service

    def test_condition_folder_delete_and_move_use_structure_permission(self):
        handler, access, write_service = self._condition_structure_handler(
            {Feature.DELETE_CONDITION, Feature.EDIT_CONDITION}
        )
        handler.on_folder_delete_requested(["folder-1"])
        handler.on_move_condition_to_folder("cond-1", "folder-2")
        self.assertEqual(write_service.deleted_folders, [])
        self.assertEqual(write_service.condition_updates, [])
        self.assertEqual(
            access.checked,
            [
                Feature.EDIT_CONDITION_STRUCTURE,
                Feature.EDIT_CONDITION_STRUCTURE,
            ],
        )
        handler, access, write_service = self._condition_structure_handler(
            {Feature.EDIT_CONDITION_STRUCTURE}
        )
        handler.on_folder_delete_requested(["folder-1"])
        handler.on_move_condition_to_folder("cond-1", "folder-2")
        self.assertEqual(write_service.deleted_folders, [("db.mdb", ["folder-1"])])
        self.assertEqual(len(write_service.condition_updates), 1)
        _file_path, _bid_uid, condition_uid, dto = write_service.condition_updates[0]
        self.assertEqual(condition_uid, "cond-1")
        self.assertEqual(dto.get_changes()["folder_uid"], "folder-2")
        self.assertEqual(
            access.checked,
            [
                Feature.EDIT_CONDITION_STRUCTURE,
                Feature.EDIT_CONDITION_STRUCTURE,
            ],
        )

    def test_batch_condition_field_update_reloads_once_after_loop(self):
        access = _FakeAccess({Feature.EDIT_CONDITION})
        write_service = _ConditionStructureWriteService()
        coordinator = SimpleNamespace(
            ui_access_manager=access,
            conditions_sidebar=None,
            refresh_conditions_ui=lambda: None,
            highlight_sidebar=lambda _uids: None,
        )
        ui_state = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("db.mdb", "bid-1")
        )
        project_data = SimpleNamespace(get_bid_conditions=lambda: {})
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=write_service,
            project_read_service=None,
            project_data=project_data,
            ui_state_manager=ui_state,
        )
        handler.on_condition_layer_change_requested(["cond-1", "cond-2"], "layer-1")
        self.assertEqual(len(write_service.condition_updates), 2)
        self.assertEqual(
            [
                call.get("reload_database")
                for call in write_service.condition_update_kwargs
            ],
            [False, False],
        )
        self.assertEqual(write_service.reloads, ["db.mdb"])

    def test_text_annotation_edit_mode_blocks_conflicting_actions(self):
        project_data = _ProjectData()
        manager = self._access_manager(project_data)
        self.assertTrue(manager.is_allowed(Feature.EDIT_PROJECT_TREE_STRUCTURE))
        self.assertTrue(manager.is_allowed(Feature.EDIT_CONDITION_STRUCTURE))
        self.assertTrue(manager.is_allowed(Feature.SELECT_PLAN_ITEMS))
        self.assertTrue(manager.is_allowed(Feature.PLACE_PLAN_ITEMS))
        self.assertTrue(manager.is_allowed(Feature.EDIT_ANNOTATION_TEXT))
        manager.set_text_annotation_edit_active(True)
        self.assertFalse(manager.is_allowed(Feature.EDIT_PROJECT_TREE_STRUCTURE))
        self.assertFalse(manager.is_allowed(Feature.EDIT_CONDITION_STRUCTURE))
        self.assertFalse(manager.is_allowed(Feature.SELECT_PLAN_ITEMS))
        self.assertFalse(manager.is_allowed(Feature.PLACE_PLAN_ITEMS))
        self.assertTrue(manager.is_allowed(Feature.EDIT_ANNOTATION_TEXT))

    def test_exiting_text_edit_reenables_shell_controls_without_page_switch(self):
        project_data = _ProjectData()
        ui_state = _ToolbarUiState(project_data.bid_ref)
        manager = self._access_manager(project_data, ui_state)
        toolbar = ToolbarStateCoordinator(ui_state, manager, project_data)
        cover_sheet_button = _FakeAction()
        layers_sidebar = _FakeLayersSidebar()
        toolbar.set_cover_sheet_button(cover_sheet_button)
        toolbar.set_bid_layers_sidebar(layers_sidebar)
        toolbar.set_plan_view(_FakePlanView())
        toolbar.set_tab_widget(_FakeTabWidget(TAB_INDEX_TAKEOFF))
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_access_manager = manager
        coordinator._update_export_menu_state = toolbar.refresh
        coordinator._on_text_annotation_edit_mode_changed(True)
        self.assertFalse(manager.is_allowed(Feature.COVER_SHEET))
        self.assertFalse(cover_sheet_button.enabled)
        self.assertFalse(layers_sidebar.interactive)
        coordinator._on_text_annotation_edit_mode_changed(False)
        self.assertTrue(manager.is_allowed(Feature.COVER_SHEET))
        self.assertTrue(cover_sheet_button.enabled)
        self.assertTrue(layers_sidebar.interactive)

    def test_takeoff_tab_delete_toolbar_uses_plan_item_selection_permission(self):
        project_data = _ProjectData()
        project_data.locked = True
        ui_state = _ToolbarUiState(project_data.bid_ref)
        manager = self._access_manager(project_data, ui_state)
        coordinator = ToolbarStateCoordinator(ui_state, manager, project_data)
        delete_action = _FakeAction()
        coordinator.set_delete_action(delete_action)
        coordinator.set_plan_view(_FakePlanView())
        coordinator.set_tab_widget(_FakeTabWidget(TAB_INDEX_TAKEOFF))
        coordinator.refresh()
        self.assertFalse(delete_action.enabled)

    def test_dimension_toolbar_uses_place_plan_items_permission(self):
        project_data = _ProjectData()
        ui_state = _ToolbarUiState(project_data.bid_ref)
        manager = self._access_manager(project_data, ui_state)
        coordinator = ToolbarStateCoordinator(ui_state, manager, project_data)
        dimension_action = _FakeAction()
        plan_view = _FakePlanView()
        coordinator.set_dimension_action(dimension_action)
        coordinator.set_plan_view(plan_view)
        coordinator.set_tab_widget(_FakeTabWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_view_stack(_FakeTabWidget(1))
        coordinator.refresh()
        self.assertTrue(dimension_action.enabled)
        project_data.locked = True
        coordinator.refresh()
        self.assertFalse(dimension_action.enabled)
        project_data.locked = False
        manager.set_text_annotation_edit_active(True)
        coordinator.refresh()
        self.assertFalse(dimension_action.enabled)
        manager.set_text_annotation_edit_active(False)
        plan_view.current_page_uid = None
        coordinator.refresh()
        self.assertFalse(dimension_action.enabled)
        plan_view.current_page_uid = "page-1"
        coordinator.refresh()
        self.assertTrue(dimension_action.enabled)

    def test_takeoff_shortcuts_do_not_run_when_selection_access_denied(self):
        project_data = _ProjectData()
        project_data.locked = True
        ui_state = _ToolbarUiState(project_data.bid_ref)
        manager = self._access_manager(project_data, ui_state)
        window = MainWindow.__new__(MainWindow)
        window.tab_widget = _FakeTabWidget(TAB_INDEX_TAKEOFF)
        window.ui_access_manager = manager
        window.plan_view = _FakePlanView()
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(refresh_toolbar=lambda: None)
        )
        MainWindow._delete_selected(window)
        MainWindow._select_all(window)
        self.assertEqual(window.plan_view.deleted, 0)
        self.assertEqual(window.plan_view.selected_all, 0)

    def test_shared_menu_callback_respects_enabled_state(self):
        controller = MenuController.__new__(MenuController)
        calls = []
        controller._get_menu_callbacks = lambda: {"blocked": lambda: calls.append(1)}
        controller.is_context_command_enabled = lambda _key: False
        MenuController.trigger_menu_callback(controller, "blocked")
        self.assertEqual(calls, [])

    def test_locked_bid_blocks_condition_edits_at_write_service(self):
        project_data = _ProjectData()
        project_data.locked = True
        service, _, _, _ = _write_service(project_data)
        result = service.update_condition(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            "12",
            UpdateConditionDto(),
        )
        self.assertFalse(result.success)
        self.assertEqual("The active bid is locked", result.error)

    def test_locked_bid_blocks_bid_internal_mutations_but_allows_status_change(self):
        project_data = _ProjectData()
        project_data.locked = True
        service, update_bid_job_status, _, _ = _write_service(project_data)
        self.assertEqual(
            [],
            service.insert_takeoffs(
                project_data.bid_ref.file_path,
                project_data.bid_ref.bid_uid,
                [],
            ),
        )
        self.assertFalse(
            service.save_cover_sheet(
                project_data.bid_ref.file_path,
                project_data.bid_ref.bid_uid,
                {"job_status_uid": 2},
            )
        )
        self.assertFalse(
            service.save_takeoffs_condition(
                project_data.bid_ref.file_path,
                ["12"],
                "34",
            )
        )
        self.assertTrue(
            service.update_bid_job_status(
                project_data.bid_ref.file_path,
                project_data.bid_ref.bid_uid,
                "2",
            )
        )
        self.assertEqual(1, len(update_bid_job_status.calls))

    def test_locked_bid_allows_bid_delete_and_duplicate(self):
        project_data = _ProjectData()
        project_data.locked = True
        service, _, delete_bids, duplicate_bid = _write_service(project_data)
        self.assertTrue(
            service.delete_bids(
                project_data.bid_ref.file_path, [project_data.bid_ref.bid_uid]
            )
        )
        self.assertEqual(
            "new-bid",
            service.duplicate_bid(
                project_data.bid_ref.file_path, project_data.bid_ref.bid_uid
            ),
        )
        self.assertEqual(1, len(delete_bids.calls))
        self.assertEqual(1, len(duplicate_bid.calls))

    def test_write_service_reports_failure_when_required_reload_fails(self):
        project_data = _ProjectData()
        service, update_bid_job_status, delete_bids, duplicate_bid = _write_service(
            project_data, reload_success=False
        )
        self.assertFalse(
            service.delete_bids(
                project_data.bid_ref.file_path, [project_data.bid_ref.bid_uid]
            )
        )
        self.assertIsNone(
            service.duplicate_bid(
                project_data.bid_ref.file_path, project_data.bid_ref.bid_uid
            )
        )
        self.assertFalse(
            service.update_bid_job_status(
                project_data.bid_ref.file_path,
                project_data.bid_ref.bid_uid,
                "2",
            )
        )
        self.assertEqual(1, len(delete_bids.calls))
        self.assertEqual(1, len(duplicate_bid.calls))
        self.assertEqual(1, len(update_bid_job_status.calls))

    def test_create_project_result_distinguishes_refresh_failure_from_write_failure(
        self,
    ):
        project_data = _ProjectData()
        service, *_ = _write_service(project_data)
        create_project = _SequenceUseCase(["project-new", "project-legacy"])
        service._create_project = create_project
        service._reload_database = lambda _file_path: False
        result = service.create_project_result(project_data.bid_ref.file_path, "New")
        self.assertFalse(result)
        self.assertTrue(result.write_success)
        self.assertTrue(result.refresh_failed)
        self.assertEqual(result.value, "project-new")
        self.assertIsNone(
            service.create_project(project_data.bid_ref.file_path, "Legacy")
        )

    def test_duplicate_bid_result_keeps_created_uid_when_refresh_fails(self):
        project_data = _ProjectData()
        service, *_ = _write_service(project_data, reload_success=False)
        result = service.duplicate_bid_result(
            project_data.bid_ref.file_path, project_data.bid_ref.bid_uid
        )
        self.assertFalse(result)
        self.assertTrue(result.write_success)
        self.assertTrue(result.refresh_failed)
        self.assertEqual(result.value, "new-bid")

    def test_new_folder_warns_when_create_succeeds_but_refresh_fails(self):
        warnings = []
        criticals = []
        renames = []
        controller = MenuController.__new__(MenuController)
        controller.window = SimpleNamespace(
            project_view=SimpleNamespace(
                schedule_rename=lambda uid: renames.append(uid)
            )
        )
        controller.ui_access_manager = SimpleNamespace(
            can_create_project_tree_items=lambda has_file: has_file
        )
        controller.ui_state_manager = SimpleNamespace(
            selected_file_path="db.mdb",
            selected_project_uid=None,
        )
        controller.project_data = SimpleNamespace()
        controller._project_write_service = SimpleNamespace(
            create_project_result=lambda _path, _name: WriteReloadResult(
                "project-new", write_success=True, reload_success=False
            )
        )
        from ost_visualizer.presentation.controllers import menu_controller

        old_warning = menu_controller.show_warning
        old_critical = menu_controller.show_critical
        menu_controller.show_warning = lambda *_args: warnings.append(_args)
        menu_controller.show_critical = lambda *_args: criticals.append(_args)
        try:
            MenuController._new_folder(controller)
        finally:
            menu_controller.show_warning = old_warning
            menu_controller.show_critical = old_critical
        self.assertEqual(len(warnings), 1)
        self.assertIn(
            "created, but the project tree could not be refreshed", warnings[0][2]
        )
        self.assertEqual(criticals, [])
        self.assertEqual(renames, [])

    def test_batch_layer_delete_reports_partial_success_and_reloads_once(self):
        project_data = _ProjectData()
        service, *_ = _write_service(project_data)
        delete_layer = _SequenceUseCase([True, False])
        reload_calls = []
        service._delete_layer = delete_layer
        service._reload_database = (
            lambda file_path: reload_calls.append(file_path) or True
        )
        result = service.delete_layers(
            project_data.bid_ref.file_path, ["layer-1", "layer-2"]
        )
        self.assertFalse(result)
        self.assertTrue(result.any_success)
        self.assertTrue(result.partial_success)
        self.assertEqual(result.succeeded_uids, ["layer-1"])
        self.assertEqual(result.failed_uids, ["layer-2"])
        self.assertEqual(len(delete_layer.calls), 2)
        self.assertEqual(reload_calls, [project_data.bid_ref.file_path])

    def test_save_bid_areas_requires_uid_map_for_new_area(self):
        project_data = _ProjectData()
        service, *_ = _write_service(project_data)
        service._save_bid_areas = _UseCase({})
        changes = BidAreaChangeset(
            new=[
                BidArea(
                    uid="new_0",
                    bid_uid=project_data.bid_ref.bid_uid,
                    parent_uid="",
                    name="Area 2",
                    sequence=0,
                )
            ],
            updated=[],
            deleted_uids=[],
        )
        self.assertIsNone(
            service.save_bid_areas(
                project_data.bid_ref.file_path,
                project_data.bid_ref.bid_uid,
                changes,
            )
        )

    def test_save_bid_areas_reports_reload_failure_for_existing_changes(self):
        project_data = _ProjectData()
        service, *_ = _write_service(project_data, reload_success=False)
        service._save_bid_areas = _UseCase({})
        changes = BidAreaChangeset(
            new=[],
            updated=[
                BidArea(
                    uid="area-1",
                    bid_uid=project_data.bid_ref.bid_uid,
                    parent_uid="",
                    name="Area 1",
                    sequence=0,
                )
            ],
            deleted_uids=[],
        )
        self.assertIsNone(
            service.save_bid_areas(
                project_data.bid_ref.file_path,
                project_data.bid_ref.bid_uid,
                changes,
            )
        )


if __name__ == "__main__":
    unittest.main()
