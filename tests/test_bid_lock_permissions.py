import logging
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PySide6 import QtWidgets
from shiboken6 import delete
from ost_visualizer.application.dtos.update_condition_dto import (
    UpdateConditionDto,
    UpdateConditionResultDto,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    DatabaseMutationResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceRef,
    SynchronizationConflict,
    SynchronizationConflictKind,
)
from ost_visualizer.application.services.active_bid_write_guard import (
    ActiveBidWriteGuard,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.project_write_service import (
    DeleteValidationResult,
    ProjectWriteService,
    WriteReloadResult,
)
from ost_visualizer.domain.entities.area import BidArea, BidAreaChangeset
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.project_data_service import ProjectDataService
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
from ost_visualizer.presentation.handlers.project_write_handler import (
    ProjectWriteHandler,
)
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.components.project_tree_view import _BidTreeWidget
from ost_visualizer.presentation.managers.ui_access_manager import (
    Feature,
    MAIN_PLAN_SURFACE_ID,
    UIAccessManager,
    _DATABASE_EDIT_FEATURES,
)
from ost_visualizer.presentation.services.bid_clipboard_service import (
    BidClipboardService,
)
from tests.workspace_state_test_support import make_workspace_state_model


class _EventBus:
    def __init__(self):
        self.subscriptions = []
        self.published = []

    def subscribe(self, event_type, callback):
        self.subscriptions.append((event_type, callback))

    def unsubscribe(self, event_type, callback):
        self.subscriptions.remove((event_type, callback))

    def publish(self, event_type, **call_options):
        self.published.append((event_type, call_options))


class _License:
    def has_valid_license(self):
        return True


class _TransactionMonitor:
    def is_ost_active(self):
        return False


class _DatabaseCapability:
    def __init__(self, editable=True):
        self.editable = editable
        self.locators = []

    def is_editable(self, locator, _resource=None):
        self.locators.append(locator)
        return self.editable


class _MutationRecorder:
    def record(self, resource, operation, *, changed_fields=(), payload=""):
        pass


class _MutationExecutor:
    def execute(self, request, operation):
        return DatabaseMutationResult(
            operation_id=request.operation_id,
            outcome_status=MutationOutcomeStatus.COMMITTED,
            value=operation(_MutationRecorder()),
        )


class _SessionRegistry:
    def get(self, _database_id):
        return ""

    def lock_tokens(self, _database_id, _resources):
        return ()


class _ConcurrencyTokens:
    def mutation_scope(self, _database_id):
        return nullcontext()

    def ensure_resources_loaded(self, _database_id, _resources):
        pass

    def expected_versions(self, _database_id, _resources):
        return ()

    def apply_result(self, _database_id, _versions):
        pass


class _ProjectData:
    def __init__(self):
        self.locked = False
        self.bid_ref = BidRef(file_path="C:/jobs/test.mdb", bid_uid="7")
        self.project_uid = "project-1"
        self.annotation_layer_visible = True
        self.conditions = {}
        self.takeoffs = []

    def is_current_bid_locked(self):
        return self.locked

    def get_current_bid_ref(self):
        return self.bid_ref

    def get_bid_conditions(self):
        return dict(self.conditions)

    def get_all_takeoffs(self):
        return list(self.takeoffs)

    def is_annotation_layer_visible(self):
        return self.annotation_layer_visible

    def find_project_uid_for_bid(self, bid_ref):
        if bid_ref == self.bid_ref:
            return self.project_uid
        return None

    def get_hierarchy(self):
        return _hierarchy_with_bids(self.bid_ref.bid_uid)


def _hierarchy_with_bids(*bid_uids, file_path="C:/jobs/test.mdb"):
    return HierarchyData(
        loaded_files=[
            HierarchyFileEntry(
                file_path=file_path,
                bid_projects={
                    "project-1": HierarchyProjectInfo(
                        name="Project 1",
                        bids=[HierarchyBidInfo(uid=uid) for uid in bid_uids],
                    )
                },
            )
        ]
    )


class _UiState:
    def __init__(self, bid_ref):
        self._bid_ref = bid_ref
        self.selected_file_path = bid_ref.file_path
        self.selected_project_uid = None
        self.place_condition_uid = None
        self.selected_page_uids = ["page-1"]
        self.active_page_uid = "page-1"
        self.highlighted_condition_uids = set()

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

    def isEnabled(self):
        return bool(self.enabled)


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

    def set_copy_enabled(self, _enabled):
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
        self.inline_edit_enabled = []

    def selected_takeoff_condition_uid(self):
        return None

    def set_selection_enabled(self, _enabled):
        pass

    def set_editing_enabled(self, _enabled):
        pass

    def set_text_annotation_inline_edit_enabled(self, enabled):
        self.inline_edit_enabled.append(bool(enabled))

    def can_move_overlay_image(self):
        return False

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

    def execute(self, *args, **call_options):
        self.calls.append((args, call_options))
        return self.result


class _SequenceUseCase:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def execute(self, *args, **call_options):
        self.calls.append((args, call_options))
        if self.results:
            return self.results.pop(0)
        return False


class _ForbiddenUseCase:
    def execute(self, *args, **call_options):
        raise AssertionError("locked bid guard did not block the write")


class _FakeAccess:
    def __init__(self, allowed):
        self.allowed = set(allowed)
        self.checked = []

    def is_allowed(self, feature):
        self.checked.append(feature)
        return feature in self.allowed

    def is_project_bid_clipboard_allowed(self, feature):
        self.checked.append(feature)
        return feature in self.allowed

    def subscribe_access_state_changed(self, _callback):
        pass

    def unsubscribe_access_state_changed(self, _callback):
        pass


class _ConditionStructureWriteService:
    def __init__(self):
        self.deleted_folders = []
        self.condition_updates = []
        self.condition_update_options = []
        self.reloads = []

    @staticmethod
    def uses_sql_collaboration_mutations(_database_id):
        return False

    def delete_condition_folders(self, file_path, folder_uids):
        self.deleted_folders.append((file_path, list(folder_uids)))
        return True

    def validate_condition_folder_delete(self, _file_path, _bid_uid, folder_uids):
        return DeleteValidationResult(
            requested_uids=list(folder_uids),
            blocked_uids=[],
        )

    def delete_condition_folders_result(self, file_path, bid_uid, folder_uids):
        self.deleted_folders.append((file_path, list(folder_uids)))
        return WriteReloadResult(list(folder_uids), True, True)

    def update_condition(
        self,
        db_path,
        bid_uid,
        condition_uid,
        updates,
        publish_database_refreshed_after_write=True,
    ):
        self.condition_updates.append((db_path, bid_uid, condition_uid, updates))
        self.condition_update_options.append(
            {
                "publish_database_refreshed_after_write": (
                    publish_database_refreshed_after_write
                )
            }
        )
        return SimpleNamespace(success=True)

    def reload_conditions_and_notify(
        self, file_path, bid_uid, condition_uids, changed_fields, change_operations
    ):
        self.reloads.append(
            (
                file_path,
                bid_uid,
                list(condition_uids),
                list(changed_fields),
                list(change_operations),
            )
        )
        return True


class _ConditionDuplicateRefreshFailedWriteService:
    def __init__(self):
        self.calls = []

    @staticmethod
    def uses_sql_collaboration_mutations(_database_id):
        return False

    def duplicate_conditions_result(self, file_path, bid_uid, condition_uids):
        self.calls.append((file_path, bid_uid, list(condition_uids)))
        return WriteReloadResult(
            ["condition-copy"], write_success=True, reload_success=False
        )


class _PartialPasteWriteService:
    def __init__(self):
        self.duplicate_results = ["copy-1", None]
        self.duplicate_calls = []
        self.reloads = []
        self.notifications = []

    @staticmethod
    def uses_sql_collaboration_mutations(_database_id):
        return False

    def duplicate_bid(self, file_path, bid_uid, reload=False):
        self.duplicate_calls.append((file_path, bid_uid, reload))
        if self.duplicate_results:
            return self.duplicate_results.pop(0)
        return None

    def move_bids(
        self,
        db_path,
        bid_uids,
        target_project_uid,
        orig_project_uid=None,
        publish_database_refreshed_after_write=True,
    ):
        raise AssertionError("same-project paste should not move copied bids")

    def reload_database(self, file_path):
        self.reloads.append(file_path)
        return True

    def notify_database_refreshed(self, file_path):
        self.notifications.append(file_path)


class _MoveToDeletedWriteService:
    def __init__(self, ui_state):
        self.ui_state = ui_state
        self.move_calls = []
        self.delete_calls = []
        self.reloads = []
        self.notifications = []
        self.selected_bid_during_reload = []
        self.selected_bid_during_notify = []

    @staticmethod
    def uses_sql_collaboration_mutations(_database_id):
        return False

    def move_bids(
        self,
        file_path,
        uids,
        target_project_uid,
        orig_project_uid=None,
        publish_database_refreshed_after_write=True,
    ):
        self.move_calls.append(
            (
                file_path,
                list(uids),
                target_project_uid,
                orig_project_uid,
                publish_database_refreshed_after_write,
            )
        )
        return True

    def delete_bids(self, file_path, uids, publish_database_refreshed_after_write=True):
        self.delete_calls.append(
            (file_path, list(uids), publish_database_refreshed_after_write)
        )
        return True

    def reload_database(self, file_path):
        self.selected_bid_during_reload.append(self.ui_state.get_selected_bid_ref())
        self.reloads.append(file_path)
        return True

    def notify_database_refreshed(self, file_path):
        self.selected_bid_during_notify.append(self.ui_state.get_selected_bid_ref())
        self.notifications.append(file_path)


class _QueuedHierarchyDeleteWriteService:
    def __init__(self):
        self.callbacks = []

    @staticmethod
    def uses_sql_collaboration_mutations(_database_id):
        return True

    def queue_bids_move(
        self,
        _file_path,
        _uids,
        _target_project_uid,
        callback,
        **_options,
    ):
        self.callbacks.append(callback)

    def queue_projects_delete(self, _file_path, _uids, callback):
        self.callbacks.append(callback)

    def queue_bids_duplicate(
        self,
        _file_path,
        _uids,
        _target_project_uid,
        callback,
    ):
        self.callbacks.append(callback)


class _DeleteBidUiState:
    def __init__(self, bid_ref):
        self._bid_ref = bid_ref
        self.selected_file_path = bid_ref.file_path
        self.selected_project_uid = None
        self.selected_project_uids = []

    def get_selected_bid_ref(self):
        return self._bid_ref

    def get_selected_bid_refs(self):
        return [self._bid_ref] if self._bid_ref else []

    def set_bid_selection(self, bid_ref):
        self._bid_ref = bid_ref

    def set_file_path(self, file_path):
        self.selected_file_path = file_path

    def set_project_uid(self, project_uid):
        self.selected_project_uid = project_uid
        self.selected_project_uids = [project_uid] if project_uid else []

    def set_database_selected(self, selected, file_path=None):
        self.selected_file_path = file_path if selected else None


class _FakeDeferredPersistence:
    def __init__(self):
        self.cancelled_bid_selected_pages = []
        self.cancelled_bid_selected_page_files = []
        self.flushes = []

    def cancel_bid_selected_pages(self, file_path, bid_uids):
        self.cancelled_bid_selected_pages.append((file_path, list(bid_uids)))

    def cancel_bid_selected_pages_for_file(self, file_path):
        self.cancelled_bid_selected_page_files.append(file_path)

    def flush_for_file(self, _file_path):
        self.flushes.append(_file_path)
        return True


class _DeferredPersistenceRequiringBidCancel(_FakeDeferredPersistence):
    def __init__(self, blocked_file_path, blocked_bid_uid):
        super().__init__()
        self.blocked_file_path = blocked_file_path
        self.blocked_bid_uid = blocked_bid_uid

    def flush_for_file(self, file_path):
        super().flush_for_file(file_path)
        return (
            self.blocked_file_path,
            [self.blocked_bid_uid],
        ) in self.cancelled_bid_selected_pages


class _DeferredPersistenceRequiringSelectedPageFileCancel(_FakeDeferredPersistence):
    def __init__(self, blocked_file_path):
        super().__init__()
        self.blocked_file_path = blocked_file_path

    def flush_for_file(self, file_path):
        super().flush_for_file(file_path)
        return (
            file_path != self.blocked_file_path
            or file_path in self.cancelled_bid_selected_page_files
        )


def _write_service(
    project_data,
    reload_success=True,
    save_takeoffs_condition=None,
    database_capability=None,
    event_bus=None,
):
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
        save_takeoffs_condition=save_takeoffs_condition or forbidden,
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
        save_page_overlay_rect=forbidden,
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
        delete_annotations=forbidden,
        insert_annotations=forbidden,
        save_annotation_positions=forbidden,
        save_annotation_text_properties=forbidden,
        save_annotation_styles=forbidden,
        reload_database=lambda _file_path: reload_success,
        event_bus=event_bus or _EventBus(),
        logger=logger,
        bid_write_guard=ActiveBidWriteGuard(project_data, logger),
        project_data_service=project_data,
        mutation_executor=_MutationExecutor(),
        session_registry=_SessionRegistry(),
        concurrency_tokens=_ConcurrencyTokens(),
        database_capability_service=database_capability or _DatabaseCapability(),
        sql_collaboration_provider=lambda: SimpleNamespace(
            uses_sql_collaboration=lambda _database_id: False,
        ),
    )
    return service, update_bid_job_status, delete_bids, duplicate_bid


class BidLockPermissionTests(unittest.TestCase):
    def test_ui_access_constructor_rolls_back_subscriptions_when_refresh_fails(self):
        event_bus = _EventBus()

        class FailingTransactionMonitor:
            def is_ost_active(self):
                raise RuntimeError("OST status unavailable")

        with self.assertRaisesRegex(RuntimeError, "OST status unavailable"):
            UIAccessManager(
                event_bus,
                _License(),
                FailingTransactionMonitor(),
                SimpleNamespace(),
                SimpleNamespace(),
                _DatabaseCapability(),
            )
        self.assertEqual(event_bus.subscriptions, [])

    def test_ui_access_cleanup_retries_only_failed_unsubscriptions(self):
        class TransientEventBus(_EventBus):
            def __init__(self):
                super().__init__()
                self.failed_once = False

            def unsubscribe(self, event_type, callback):
                if (
                    event_type is AppEvents.LICENSE_STATUS_CHANGED
                    and not self.failed_once
                ):
                    self.failed_once = True
                    raise RuntimeError("temporary unsubscribe failure")
                super().unsubscribe(event_type, callback)

        event_bus = TransientEventBus()
        manager = UIAccessManager(
            event_bus,
            _License(),
            _TransactionMonitor(),
            _ProjectData(),
            _UiState(BidRef("test.mdb", "bid-1")),
            _DatabaseCapability(),
        )
        with self.assertRaises(ExceptionGroup):
            manager.cleanup()
        self.assertEqual(
            [event_type for event_type, _callback in manager._subscriptions],
            [AppEvents.LICENSE_STATUS_CHANGED],
        )
        manager.cleanup()
        self.assertEqual(event_bus.subscriptions, [])
        self.assertEqual(manager._subscriptions, [])
        self.assertIsNone(manager._event_bus)

    def test_area_dialog_without_selected_bid_has_no_stale_presence_reference(self):
        source = Path(
            "ost_visualizer/presentation/coordinators/ui_event_coordinator.py"
        ).read_text(encoding="utf-8")
        method = source.split("    def open_areas_dialog", 1)[1].split(
            "    def _save_bid_areas_from_dialog", 1
        )[0]
        self.assertNotIn("prev_bid_ref", method)

    def _access_manager(self, project_data, ui_state=None, capability=None):
        return UIAccessManager(
            _EventBus(),
            _License(),
            _TransactionMonitor(),
            project_data,
            ui_state or _UiState(project_data.bid_ref),
            capability or _DatabaseCapability(),
        )

    def test_database_edit_features_are_complete_and_selection_is_read_only(self):
        self.assertEqual(
            _DATABASE_EDIT_FEATURES,
            frozenset(
                {
                    Feature.DELETE_BID,
                    Feature.DUPLICATE_BID,
                    Feature.EDIT_PROJECT_TREE_STRUCTURE,
                    Feature.EDIT_CONDITION_STRUCTURE,
                    Feature.IMPORT,
                    Feature.COVER_SHEET,
                    Feature.EDIT_PAGE_SETTINGS,
                    Feature.EDIT_PLAN_ITEMS,
                    Feature.PLACE_PLAN_ITEMS,
                    Feature.PLACE_ANNOTATIONS,
                    Feature.DUPLICATE_CONDITION,
                    Feature.DELETE_CONDITION,
                    Feature.EDIT_CONDITION,
                    Feature.EDIT_BID_JOB_STATUS,
                    Feature.CREATE_DATABASE,
                    Feature.EDIT_MASTER_DATA,
                    Feature.EDIT_ANNOTATION_TEXT,
                }
            ),
        )
        self.assertNotIn(Feature.SELECT_PLAN_ITEMS, _DATABASE_EDIT_FEATURES)

    def test_read_only_database_allows_selection_but_denies_plan_item_edits(self):
        project_data = _ProjectData()
        manager = self._access_manager(
            project_data, capability=_DatabaseCapability(editable=False)
        )
        self.assertTrue(manager.is_allowed(Feature.SELECT_PLAN_ITEMS))
        self.assertTrue(manager.is_allowed(Feature.COPY_BID))
        self.assertTrue(manager.is_allowed(Feature.COPY_CONDITION))
        self.assertTrue(manager.is_allowed(Feature.VIEW_2D))
        self.assertTrue(manager.is_allowed(Feature.EXPORT))
        self.assertFalse(manager.is_allowed(Feature.EDIT_PLAN_ITEMS))
        self.assertFalse(manager.is_allowed(Feature.DUPLICATE_BID))
        self.assertFalse(manager.is_allowed(Feature.DUPLICATE_CONDITION))
        self.assertFalse(manager.is_allowed(Feature.EDIT_PAGE_SETTINGS))

    def test_bid_job_status_permission_uses_selected_bid_resource(self):
        project_data = _ProjectData()
        checked_resources = []

        class _ResourceCapability:
            def is_editable(self, _locator, resource=None):
                checked_resources.append(resource)
                return resource is None or resource.resource_id != "7"

        manager = self._access_manager(
            project_data,
            capability=_ResourceCapability(),
        )
        self.assertFalse(manager.is_allowed(Feature.EDIT_BID_JOB_STATUS))
        self.assertEqual(
            checked_resources,
            [ResourceRef("bid", "7", 7)],
        )

    def test_revoked_database_capability_blocks_deferred_write_execution(self):
        service, *_unused = _write_service(
            _ProjectData(), database_capability=_DatabaseCapability(editable=False)
        )
        self.assertTrue(service.is_expected_deferred_write_blocked("sql-db"))

    def test_unknown_feature_and_edit_without_database_are_denied(self):
        project_data = _ProjectData()
        manager = self._access_manager(project_data)
        self.assertFalse(manager.is_allowed(object()))
        manager._ui_state_manager.selected_file_path = None
        self.assertFalse(manager.is_allowed(Feature.EDIT_PLAN_ITEMS))

    def test_capability_change_refreshes_access_before_projecting_controls(self):
        calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(selected_file_path="sql-db-1")
        coordinator.ui_access_manager = SimpleNamespace(
            refresh=lambda: calls.append("refresh"),
            is_allowed=lambda feature: feature == Feature.SELECT_PLAN_ITEMS,
            is_database_editable=lambda: False,
        )
        coordinator._deferred_persistence = SimpleNamespace(
            cancel_for_file=lambda file_path: calls.append(("cancel", file_path))
        )
        coordinator.main_window = SimpleNamespace(
            menu_controller=SimpleNamespace(
                update_menu_states=lambda: calls.append("menu")
            )
        )
        coordinator._toolbar = SimpleNamespace(refresh=lambda: calls.append("toolbar"))
        coordinator._mesh_window = SimpleNamespace(
            set_pick_enabled=lambda enabled: calls.append(("mesh-pick", enabled)),
            set_editing_enabled=lambda enabled: calls.append(("mesh-edit", enabled)),
        )
        coordinator._on_database_capabilities_changed("other-db")
        self.assertEqual(calls, [])
        coordinator._on_database_capabilities_changed("sql-db-1")
        self.assertEqual(
            calls,
            [
                "refresh",
                ("cancel", "sql-db-1"),
                "menu",
                ("mesh-pick", True),
                ("mesh-edit", False),
            ],
        )

    def test_toolbar_revokes_active_inline_text_editing_with_database_access(self):
        project_data = _ProjectData()
        ui_state = _ToolbarUiState(project_data.bid_ref)
        capability = _DatabaseCapability(editable=True)
        manager = self._access_manager(project_data, ui_state, capability)
        plan_view = _FakePlanView()
        coordinator = ToolbarStateCoordinator(ui_state, manager, project_data)
        coordinator.set_plan_view(plan_view)
        coordinator.set_tab_widget(_FakeTabWidget(TAB_INDEX_TAKEOFF))
        coordinator.refresh()
        capability.editable = False
        coordinator.refresh()
        self.assertEqual(plan_view.inline_edit_enabled, [True, False])

    def test_writable_capability_refresh_does_not_discard_deferred_state(self):
        calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(selected_file_path="sql-db-1")
        coordinator.ui_access_manager = SimpleNamespace(
            refresh=lambda: calls.append("refresh"),
            is_database_editable=lambda: True,
        )
        coordinator._deferred_persistence = SimpleNamespace(
            cancel_for_file=lambda file_path: calls.append(("cancel", file_path))
        )
        coordinator._mesh_window = None
        coordinator._update_menu_state = lambda: calls.append("project")
        coordinator._on_database_capabilities_changed("sql-db-1")
        self.assertEqual(calls, ["refresh", "project"])

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

    def test_annotation_layer_visibility_blocks_only_annotation_placement(self):
        project_data = _ProjectData()
        manager = self._access_manager(project_data)
        self.assertTrue(manager.is_allowed(Feature.PLACE_PLAN_ITEMS))
        self.assertTrue(manager.is_allowed(Feature.PLACE_ANNOTATIONS))
        self.assertTrue(manager.is_allowed(Feature.EDIT_ANNOTATION_TEXT))
        project_data.annotation_layer_visible = False
        self.assertTrue(manager.is_allowed(Feature.PLACE_PLAN_ITEMS))
        self.assertFalse(manager.is_allowed(Feature.PLACE_ANNOTATIONS))
        self.assertTrue(manager.is_allowed(Feature.EDIT_ANNOTATION_TEXT))
        project_data.annotation_layer_visible = True
        self.assertTrue(manager.is_allowed(Feature.PLACE_ANNOTATIONS))
        project_data.locked = True
        self.assertFalse(manager.is_allowed(Feature.PLACE_ANNOTATIONS))
        project_data.locked = False
        manager.set_text_annotation_edit_active(True, surface_id=MAIN_PLAN_SURFACE_ID)
        self.assertFalse(manager.is_allowed(Feature.PLACE_ANNOTATIONS))

    def test_active_annotation_placement_ignores_only_its_own_area_lock(self):
        project_data = _ProjectData()
        manager = self._access_manager(project_data)
        manager.set_area_placement_active(True, surface_id=MAIN_PLAN_SURFACE_ID)
        self.assertFalse(manager.is_allowed(Feature.PLACE_ANNOTATIONS))
        self.assertTrue(
            manager.is_allowed_for_active_placement(Feature.PLACE_ANNOTATIONS)
        )
        self.assertFalse(
            manager.is_allowed_for_active_placement(Feature.EDIT_PLAN_ITEMS)
        )
        project_data.annotation_layer_visible = False
        self.assertFalse(
            manager.is_allowed_for_active_placement(Feature.PLACE_ANNOTATIONS)
        )
        project_data.annotation_layer_visible = True
        project_data.locked = True
        self.assertFalse(
            manager.is_allowed_for_active_placement(Feature.PLACE_ANNOTATIONS)
        )

    def test_split_structure_permissions_keep_existing_blockers(self):
        project_data = _ProjectData()
        manager = self._access_manager(project_data)
        self.assertTrue(manager.can_create_project_tree_items(True))
        self.assertFalse(manager.can_create_project_tree_items(False))
        self.assertTrue(manager.is_allowed(Feature.EDIT_PROJECT_TREE_STRUCTURE))
        self.assertTrue(manager.is_allowed(Feature.EDIT_CONDITION_STRUCTURE))
        manager.set_area_placement_active(True, surface_id=MAIN_PLAN_SURFACE_ID)
        self.assertFalse(manager.can_create_project_tree_items(True))
        self.assertFalse(manager.is_allowed(Feature.EDIT_PROJECT_TREE_STRUCTURE))
        self.assertFalse(manager.is_allowed(Feature.EDIT_CONDITION_STRUCTURE))
        manager.set_area_placement_active(False, surface_id=MAIN_PLAN_SURFACE_ID)
        manager.set_text_annotation_edit_active(True, surface_id=MAIN_PLAN_SURFACE_ID)
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
        manager.set_text_annotation_edit_active(True, surface_id=MAIN_PLAN_SURFACE_ID)
        coordinator.refresh()
        self.assertFalse(conditions_sidebar.create_folder_enabled)

    def _condition_structure_handler(self, allowed):
        access = _FakeAccess(allowed)
        write_service = _ConditionStructureWriteService()
        coordinator = SimpleNamespace(
            ui_access_manager=access,
            conditions_sidebar=SimpleNamespace(window=lambda: None),
            flush_deferred_for_file=lambda _file_path: True,
        )
        ui_state = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("db.mdb", "bid-1")
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=write_service,
            project_read_service=None,
            project_data=SimpleNamespace(
                get_bid_condition_folders=lambda: {
                    "folder-1": SimpleNamespace(name="Folder 1")
                }
            ),
            ui_state_manager=ui_state,
            workspace_state_model=make_workspace_state_model(),
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
        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "confirm_multi_delete",
            return_value=[("Folder 1", "folder-1")],
        ):
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
            flush_deferred_for_file=lambda _file_path: True,
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
            workspace_state_model=make_workspace_state_model(),
        )
        handler.on_condition_layer_change_requested(["cond-1", "cond-2"], "layer-1")
        self.assertEqual(len(write_service.condition_updates), 2)
        self.assertEqual(
            [
                call.get("publish_database_refreshed_after_write")
                for call in write_service.condition_update_options
            ],
            [False, False],
        )
        self.assertEqual(
            write_service.reloads,
            [
                (
                    "db.mdb",
                    "bid-1",
                    ["cond-1", "cond-2"],
                    ["layer_uid"],
                    [ChangeOperation.UPDATE],
                )
            ],
        )

    def test_condition_duplicate_refresh_failure_warns_without_placement(self):
        warnings = []
        access = _FakeAccess({Feature.DUPLICATE_CONDITION})
        write_service = _ConditionDuplicateRefreshFailedWriteService()
        placement = SimpleNamespace(entered=[])
        placement.enter = lambda *args: placement.entered.append(args)
        coordinator = SimpleNamespace(
            ui_access_manager=access,
            conditions_sidebar=None,
            placement=placement,
            _is_takeoff_2d_view_active=lambda: True,
            refresh_conditions_ui=lambda: None,
            highlight_sidebar=lambda _uids: None,
            flush_deferred_for_file=lambda _file_path: True,
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
            workspace_state_model=make_workspace_state_model(),
        )
        from ost_visualizer.presentation.handlers import condition_action_handler

        old_warning = condition_action_handler.show_warning
        condition_action_handler.show_warning = lambda *args: warnings.append(args)
        try:
            handler.on_duplicate_requested(["condition-1"])
        finally:
            condition_action_handler.show_warning = old_warning
        self.assertEqual(write_service.calls, [("db.mdb", "bid-1", ["condition-1"])])
        self.assertEqual(placement.entered, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("could not be refreshed", warnings[0][2])

    def test_text_annotation_edit_mode_blocks_conflicting_actions(self):
        project_data = _ProjectData()
        manager = self._access_manager(project_data)
        self.assertTrue(manager.is_allowed(Feature.EDIT_PROJECT_TREE_STRUCTURE))
        self.assertTrue(manager.is_allowed(Feature.EDIT_CONDITION_STRUCTURE))
        self.assertTrue(manager.is_allowed(Feature.SELECT_PLAN_ITEMS))
        self.assertTrue(manager.is_allowed(Feature.PLACE_PLAN_ITEMS))
        self.assertTrue(manager.is_allowed(Feature.EDIT_ANNOTATION_TEXT))
        manager.set_text_annotation_edit_active(True, surface_id=MAIN_PLAN_SURFACE_ID)
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
        coordinator._update_menu_state = lambda: None
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

    def test_annotation_toolbar_uses_place_annotations_permission(self):
        project_data = _ProjectData()
        ui_state = _ToolbarUiState(project_data.bid_ref)
        manager = self._access_manager(project_data, ui_state)
        coordinator = ToolbarStateCoordinator(ui_state, manager, project_data)
        dimension_action = _FakeAction()
        line_action = _FakeAction()
        cloud_action = _FakeAction()
        plan_view = _FakePlanView()
        coordinator.set_annotation_tool_actions(
            [dimension_action, line_action, cloud_action]
        )
        coordinator.set_plan_view(plan_view)
        coordinator.set_tab_widget(_FakeTabWidget(TAB_INDEX_TAKEOFF))
        coordinator.set_view_stack(_FakeTabWidget(1))
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

    def test_shared_menu_annotation_tools_use_place_annotations_permission(self):
        project_data = _ProjectData()
        manager = self._access_manager(project_data)
        dimension_action = _FakeAction()
        dimension_action.enabled = True
        place_action = _FakeAction()
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

    def test_project_tree_drag_restore_and_move_use_structure_permission(self):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.assertIsNotNone(app)
        access = _FakeAccess({Feature.EDIT_PROJECT_TREE_STRUCTURE})
        tree = _BidTreeWidget()
        tree.set_ui_access_manager(access)
        tree._drag_items = [object()]
        self.assertTrue(tree._move_bids_allowed())
        self.assertEqual(access.checked, [Feature.EDIT_PROJECT_TREE_STRUCTURE])
        tree.deleteLater()
        calls = []
        window = MainWindow.__new__(MainWindow)
        window.ui_access_manager = _FakeAccess(set())
        window.handlers = SimpleNamespace(
            delete=SimpleNamespace(
                restore_bids=lambda refs: calls.append(("restore", refs)),
                move_bids=lambda refs, target: calls.append(("move", refs, target)),
            )
        )
        MainWindow._restore_project_bids(window, ["bid-1"])
        MainWindow._move_project_bids(window, ["bid-1"], "project-2")
        self.assertEqual(calls, [])

    def test_shared_menu_callback_respects_enabled_state(self):
        controller = MenuController.__new__(MenuController)
        calls = []
        controller._get_menu_callbacks = lambda: {"blocked": lambda: calls.append(1)}
        controller.is_context_command_enabled = lambda _key: False
        MenuController.trigger_menu_callback(controller, "blocked")
        self.assertEqual(calls, [])

    def test_project_paste_allows_same_database_with_normalized_paths(self):
        window = MainWindow.__new__(MainWindow)
        window._bid_clipboard = BidClipboardService()
        window._bid_clipboard.copy([BidRef("C:/jobs/test.mdb", "bid-1")])
        window._project_data_service = SimpleNamespace(
            get_hierarchy=lambda: HierarchyData(
                loaded_files=[
                    HierarchyFileEntry(
                        file_path="C:\\jobs\\test.mdb",
                        bid_projects={
                            "project-1": HierarchyProjectInfo(
                                name="Project 1",
                                bids=[HierarchyBidInfo(uid="bid-1")],
                            )
                        },
                    )
                ]
            )
        )
        window.ui_access_manager = _FakeAccess({Feature.DUPLICATE_BID})
        self.assertTrue(
            MainWindow._can_paste_project_bids(
                window, "C:\\jobs\\test.mdb", "project-2"
            )
        )

    def test_context_copy_stores_bid_clipboard_with_normalized_same_database_refs(self):
        window = MainWindow.__new__(MainWindow)
        window.ui_access_manager = _FakeAccess({Feature.COPY_BID})
        window._bid_clipboard = BidClipboardService()
        refresh_calls = []
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(refresh_toolbar=lambda: refresh_calls.append(True))
        )
        MainWindow._copy_project_bids(
            window,
            [
                BidRef("C:/jobs/test.mdb", "bid-1"),
                BidRef("C:\\jobs\\test.mdb", "bid-2"),
            ],
        )
        self.assertEqual(
            [ref.bid_uid for ref in window._bid_clipboard.bid_refs],
            ["bid-1", "bid-2"],
        )
        self.assertEqual(refresh_calls, [True])

    def test_project_paste_invokes_bid_paste_handler_for_same_database_target(self):
        window = MainWindow.__new__(MainWindow)
        window._bid_clipboard = BidClipboardService()
        window._bid_clipboard.copy([BidRef("C:/jobs/test.mdb", "bid-1")])
        window._project_data_service = SimpleNamespace(
            get_hierarchy=lambda: _hierarchy_with_bids("bid-1")
        )
        window.ui_access_manager = _FakeAccess({Feature.DUPLICATE_BID})
        paste_calls = []
        refresh_calls = []
        window.handlers = SimpleNamespace(
            delete=SimpleNamespace(
                paste_bids=lambda refs, project_uid, is_cut=False: paste_calls.append(
                    ([ref.bid_uid for ref in refs], project_uid, is_cut)
                )
                or True
            ),
            ui_event=SimpleNamespace(
                refresh_toolbar=lambda: refresh_calls.append(True)
            ),
        )
        MainWindow._paste_project_bids(window, "C:\\jobs\\test.mdb", "project-2")
        self.assertEqual(paste_calls, [(["bid-1"], "project-2", False)])
        self.assertEqual(refresh_calls, [True])

    def test_project_cut_clipboard_waits_for_authoritative_move_completion(self):
        window = MainWindow.__new__(MainWindow)
        window._bid_clipboard = BidClipboardService()
        window._bid_clipboard.cut([BidRef("C:/jobs/test.mdb", "bid-1")])
        window._project_data_service = SimpleNamespace(
            get_hierarchy=lambda: _hierarchy_with_bids("bid-1")
        )
        window.ui_access_manager = _FakeAccess({Feature.DELETE_BID})
        completions = []
        refresh_calls = []

        def paste_bids(
            _refs,
            _project_uid,
            *,
            is_cut=False,
            on_cut_committed=None,
        ):
            self.assertTrue(is_cut)
            completions.append(on_cut_committed)
            return True

        window.handlers = SimpleNamespace(
            delete=SimpleNamespace(paste_bids=paste_bids),
            ui_event=SimpleNamespace(
                refresh_toolbar=lambda: refresh_calls.append(True)
            ),
        )
        MainWindow._paste_project_bids(window, "C:/jobs/test.mdb", "project-2")
        self.assertTrue(window._bid_clipboard.has_content())
        completions[0]()
        self.assertFalse(window._bid_clipboard.has_content())
        self.assertEqual(refresh_calls, [True, True])

    def test_older_bid_cut_completion_preserves_newer_clipboard(self):
        window = MainWindow.__new__(MainWindow)
        window._bid_clipboard = BidClipboardService()
        window._bid_clipboard.cut([BidRef("C:/jobs/test.mdb", "bid-1")])
        window._project_data_service = SimpleNamespace(
            get_hierarchy=lambda: _hierarchy_with_bids("bid-1", "bid-2")
        )
        window.ui_access_manager = _FakeAccess({Feature.DELETE_BID})
        completions = []

        def paste_bids(
            _refs,
            _project_uid,
            *,
            is_cut=False,
            on_cut_committed=None,
        ):
            self.assertTrue(is_cut)
            completions.append(on_cut_committed)
            return True

        window.handlers = SimpleNamespace(
            delete=SimpleNamespace(paste_bids=paste_bids),
            ui_event=SimpleNamespace(refresh_toolbar=lambda: None),
        )
        MainWindow._paste_project_bids(window, "C:/jobs/test.mdb", "project-2")
        window._bid_clipboard.cut([BidRef("C:/jobs/test.mdb", "bid-2")])
        completions[0]()
        self.assertTrue(window._bid_clipboard.is_cut)
        self.assertEqual(
            window._bid_clipboard.bid_refs,
            [BidRef("C:/jobs/test.mdb", "bid-2")],
        )

    def test_project_paste_reconciles_partial_remote_bid_deletion(self):
        window = MainWindow.__new__(MainWindow)
        window._bid_clipboard = BidClipboardService()
        window._bid_clipboard.cut(
            [
                BidRef("C:/jobs/test.mdb", "deleted-bid"),
                BidRef("C:/jobs/test.mdb", "surviving-bid"),
            ]
        )
        window._project_data_service = SimpleNamespace(
            get_hierarchy=lambda: HierarchyData(
                loaded_files=[
                    HierarchyFileEntry(
                        file_path="C:\\jobs\\test.mdb",
                        bid_projects={
                            "project-1": HierarchyProjectInfo(
                                name="Project 1",
                                bids=[HierarchyBidInfo(uid="surviving-bid")],
                            )
                        },
                    )
                ]
            )
        )
        window.ui_access_manager = _FakeAccess({Feature.DELETE_BID})
        self.assertTrue(
            MainWindow._can_paste_project_bids(window, "C:/jobs/test.mdb", "project-2")
        )
        self.assertEqual(
            [ref.bid_uid for ref in window._bid_clipboard.bid_refs],
            ["surviving-bid"],
        )

    def test_bid_clipboard_file_unload_invalidates_equivalent_source_path(self):
        clipboard = BidClipboardService()
        clipboard.cut([BidRef("C:/jobs/test.mdb", "bid-1")])
        self.assertTrue(clipboard.clear_for_file("C:\\jobs\\test.mdb"))
        self.assertFalse(clipboard.has_content())
        self.assertFalse(clipboard.is_cut)

    def test_sql_bid_cut_completion_callback_runs_only_after_commit(self):
        write_service = _QueuedHierarchyDeleteWriteService()
        committed = []
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=SimpleNamespace(),
            project_write_service=write_service,
            ui_state_manager=SimpleNamespace(),
            deferred_persistence_manager=_FakeDeferredPersistence(),
        )
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: None,
                present_queued_mutation_error=lambda *_args: None,
            )
        )
        bid_ref = BidRef("database", "bid-1")
        self.assertTrue(
            handler.paste_bids(
                [bid_ref],
                "project-2",
                is_cut=True,
                on_cut_committed=lambda: committed.append(True),
            )
        )
        write_service.callbacks[0](
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000301",
                outcome_status=MutationOutcomeStatus.REJECTED,
                commit_attempted=False,
            )
        )
        self.assertEqual(committed, [])
        self.assertTrue(
            handler.paste_bids(
                [bid_ref],
                "project-2",
                is_cut=True,
                on_cut_committed=lambda: committed.append(True),
            )
        )
        write_service.callbacks[1](
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000302",
                outcome_status=MutationOutcomeStatus.COMMITTED,
                commit_attempted=True,
            )
        )
        self.assertEqual(committed, [True])

    def test_bid_paste_handler_accepts_normalized_same_database_source_paths(self):
        write_service = _PartialPasteWriteService()
        write_service.duplicate_results = ["copy-1", "copy-2"]
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=SimpleNamespace(
                find_project_uid_for_bid=lambda _ref: "project-2"
            ),
            project_write_service=write_service,
            ui_state_manager=SimpleNamespace(),
            deferred_persistence_manager=_FakeDeferredPersistence(),
        )

        def run_progress(_label, task_fn, action_text, reporter):
            del action_text, reporter
            return QtWidgets.QDialog.DialogCode.Accepted, task_fn(), None

        handler._run_progress_dialog = run_progress
        result = handler.paste_bids(
            [
                BidRef("C:/jobs/test.mdb", "bid-1"),
                BidRef("C:\\jobs\\test.mdb", "bid-2"),
            ],
            "project-2",
        )
        self.assertTrue(result)
        self.assertEqual(
            write_service.duplicate_calls,
            [
                ("C:/jobs/test.mdb", "bid-1", False),
                ("C:/jobs/test.mdb", "bid-2", False),
            ],
        )

    def test_project_paste_allowed_when_project_target_replaces_bid_selection(self):
        project_data = _ProjectData()
        ui_state = SimpleNamespace(
            selected_file_path="C:/jobs/test.mdb",
            selected_project_uid="project-2",
            place_condition_uid=None,
            get_selected_bid_ref=lambda: None,
            is_database_selected=lambda: False,
        )
        manager = self._access_manager(project_data, ui_state)
        self.assertFalse(manager.is_allowed(Feature.DUPLICATE_BID))
        window = MainWindow.__new__(MainWindow)
        window._bid_clipboard = BidClipboardService()
        window._bid_clipboard.copy([BidRef("C:/jobs/test.mdb", "bid-1")])
        window._project_data_service = SimpleNamespace(
            get_hierarchy=lambda: _hierarchy_with_bids("bid-1")
        )
        window.ui_access_manager = manager
        self.assertTrue(
            MainWindow._can_paste_project_bids(window, "C:/jobs/test.mdb", "project-2")
        )

    def test_toolbar_paste_allows_same_database_with_normalized_paths(self):
        clipboard = BidClipboardService()
        clipboard.copy([BidRef("C:/jobs/test.mdb", "bid-1")])
        ui_state = SimpleNamespace(
            selected_file_path="C:\\jobs\\test.mdb",
            selected_project_uid="project-2",
            get_selected_bid_ref=lambda: None,
        )
        toolbar = ToolbarStateCoordinator(
            ui_state,
            _FakeAccess({Feature.DUPLICATE_BID}),
            SimpleNamespace(
                find_project_uid_for_bid=lambda _ref: None,
                get_hierarchy=lambda: _hierarchy_with_bids(
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
            get_selected_bid_ref=lambda: None,
        )
        toolbar = ToolbarStateCoordinator(
            ui_state,
            _FakeAccess({Feature.DELETE_BID}),
            SimpleNamespace(
                get_hierarchy=lambda: _hierarchy_with_bids(),
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
            get_selected_bid_ref=lambda: None,
        )
        toolbar = ToolbarStateCoordinator(
            ui_state,
            _FakeAccess({Feature.DUPLICATE_BID}),
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
        project_data = _ProjectData()
        ui_state = SimpleNamespace(
            selected_file_path="C:/jobs/test.mdb",
            selected_project_uid="project-2",
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

    def test_multi_bid_paste_partial_success_warns_without_plain_failure(self):
        write_service = _PartialPasteWriteService()
        project_data = SimpleNamespace(
            find_project_uid_for_bid=lambda _ref: "project-1",
            get_hierarchy=lambda: SimpleNamespace(find_bid_info=lambda _ref: None),
        )
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=SimpleNamespace(),
            deferred_persistence_manager=_FakeDeferredPersistence(),
        )

        def run_progress(label, task_fn, action_text, reporter):
            return QtWidgets.QDialog.DialogCode.Accepted, task_fn(), None

        handler._run_progress_dialog = run_progress
        warnings = []
        criticals = []
        from ost_visualizer.presentation.handlers import project_write_handler

        old_warning = project_write_handler.show_warning
        old_critical = project_write_handler.show_critical
        old_logger_error = project_write_handler.logger.error
        project_write_handler.show_warning = lambda *args: warnings.append(args)
        project_write_handler.show_critical = lambda *args: criticals.append(args)
        project_write_handler.logger.error = lambda *args, **call_options: None
        try:
            result = handler.paste_bids(
                [
                    BidRef("db.mdb", "bid-1"),
                    BidRef("db.mdb", "bid-2"),
                ],
                "project-1",
            )
        finally:
            project_write_handler.show_warning = old_warning
            project_write_handler.show_critical = old_critical
            project_write_handler.logger.error = old_logger_error
        self.assertTrue(result)
        self.assertEqual(
            write_service.duplicate_calls,
            [
                ("db.mdb", "bid-1", False),
                ("db.mdb", "bid-2", False),
            ],
        )
        self.assertEqual(write_service.reloads, ["db.mdb"])
        self.assertEqual(write_service.notifications, ["db.mdb"])
        self.assertEqual(len(warnings), 1)
        self.assertIn("Some bids were pasted", warnings[0][2])
        self.assertEqual(len(criticals), 0)

    def test_duplicate_stops_after_progress_dialog_destroys_main_window(self):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        window = QtWidgets.QWidget()
        bid_ref = BidRef("db.mdb", "bid-1")
        handler = ProjectWriteHandler(
            window=window,
            project_data_service=SimpleNamespace(
                get_hierarchy=lambda: SimpleNamespace(
                    find_bid_info=lambda _ref: SimpleNamespace(name="Bid 1")
                )
            ),
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _path: False
            ),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: bid_ref),
            deferred_persistence_manager=_FakeDeferredPersistence(),
        )

        def destroy_window(*_args, **_kwargs):
            delete(window)
            return QtWidgets.QDialog.DialogCode.Rejected, None, None

        handler._run_progress_dialog = destroy_window
        criticals = []
        with patch(
            "ost_visualizer.presentation.handlers.project_write_handler.show_critical",
            side_effect=lambda *args: criticals.append(args),
        ):
            handler.duplicate_selected()
        self.assertEqual(len(criticals), 0)
        app.processEvents()

    def test_paste_stops_after_progress_dialog_destroys_main_window(self):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        window = QtWidgets.QWidget()
        bid_ref = BidRef("db.mdb", "bid-1")
        handler = ProjectWriteHandler(
            window=window,
            project_data_service=SimpleNamespace(
                find_project_uid_for_bid=lambda _ref: "project-1",
                get_hierarchy=lambda: SimpleNamespace(
                    find_bid_info=lambda _ref: SimpleNamespace(name="Bid 1")
                ),
            ),
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _path: False
            ),
            ui_state_manager=SimpleNamespace(),
            deferred_persistence_manager=_FakeDeferredPersistence(),
        )

        def destroy_window(*_args, **_kwargs):
            delete(window)
            return QtWidgets.QDialog.DialogCode.Rejected, None, None

        handler._run_progress_dialog = destroy_window
        criticals = []
        with patch(
            "ost_visualizer.presentation.handlers.project_write_handler.show_critical",
            side_effect=lambda *args: criticals.append(args),
        ):
            result = handler.paste_bids([bid_ref], "project-2")
        self.assertFalse(result)
        self.assertEqual(len(criticals), 0)
        app.processEvents()

    def test_sql_hierarchy_pending_keys_are_database_scoped_and_recovery_safe(self):
        callbacks = {}
        committed = []
        errors = []
        refreshes = []
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=SimpleNamespace(),
            project_write_service=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(),
            deferred_persistence_manager=_FakeDeferredPersistence(),
        )
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: refreshes.append(True),
                present_queued_mutation_error=lambda *args: errors.append(args),
            )
        )

        def submit(database_id):
            return handler._submit_sql_hierarchy_operation(
                database_id,
                ("move_bids", "7"),
                "Move Bids",
                lambda callback: callbacks.__setitem__(database_id, callback),
                lambda _result: committed.append(database_id),
            )

        self.assertTrue(submit("database-a"))
        self.assertTrue(submit("database-b"))
        key_a = ("database-a", "move_bids", "7")
        key_b = ("database-b", "move_bids", "7")
        self.assertIn(key_a, handler._pending_sql_operations)
        self.assertIn(key_b, handler._pending_sql_operations)
        for status in (
            MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        ):
            callbacks["database-a"](
                QueuedMutationResult(
                    database_id="database-a",
                    runtime_generation=1,
                    operation_id="00000000-0000-0000-0000-000000000001",
                    outcome_status=status,
                    commit_attempted=True,
                )
            )
            self.assertIn(key_a, handler._pending_sql_operations)
            self.assertEqual(errors, [])
            self.assertEqual(refreshes, [])
        callbacks["database-a"](
            QueuedMutationResult(
                database_id="database-a",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000001",
                outcome_status=MutationOutcomeStatus.COMMITTED,
                commit_attempted=True,
            )
        )
        self.assertNotIn(key_a, handler._pending_sql_operations)
        self.assertIn(key_b, handler._pending_sql_operations)
        self.assertEqual(committed, ["database-a"])

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

    def test_condition_update_preserves_typed_session_conflict_reason(self):
        project_data = _ProjectData()
        service, _, _, _ = _write_service(project_data)
        resource = ResourceRef("condition", "12", int(project_data.bid_ref.bid_uid))
        service._mutation_executor = SimpleNamespace(
            execute=lambda request, _operation: DatabaseMutationResult(
                operation_id=request.operation_id,
                outcome_status=MutationOutcomeStatus.CONFLICT,
                conflict=SynchronizationConflict(
                    database_id=project_data.bid_ref.file_path,
                    resource=resource,
                    reason="The SQL collaboration session expired.",
                    kind=SynchronizationConflictKind.SESSION,
                ),
            )
        )
        result = service.update_condition(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            "12",
            UpdateConditionDto(),
        )
        self.assertFalse(result.success)
        self.assertEqual("The SQL collaboration session expired.", result.error)

    def test_mdb_condition_update_publishes_targeted_fields_without_database_refresh(
        self,
    ):
        project_data = _ProjectData()
        events = _EventBus()
        service, _, _, _ = _write_service(project_data, event_bus=events)
        service._update_condition = _UseCase(UpdateConditionResultDto(success=True))
        updates = UpdateConditionDto()
        updates.set("name", "Level 2 (Top: 12'-0\")")
        updates.set("z_value", 144.0)
        result = service.update_condition(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            "12",
            updates,
        )
        self.assertTrue(result.success)
        self.assertEqual(
            events.published,
            [
                (
                    AppEvents.CONDITIONS_CHANGED,
                    {
                        "database_id": project_data.bid_ref.file_path,
                        "bid_uid": project_data.bid_ref.bid_uid,
                        "condition_uids": ["12"],
                        "changed_fields": ["name", "z_value"],
                        "change_operations": ["update"],
                        "invalidates_undo": False,
                    },
                )
            ],
        )

    def test_condition_name_elevation_metadata_is_classified_for_mesh_refresh(self):
        project_data = _ProjectData()
        project_data.conditions["12"] = Condition(uid="12", name="Walls @T 10' - 0\"")
        events = _EventBus()
        service, _, _, _ = _write_service(project_data, event_bus=events)
        service._update_condition = _UseCase(UpdateConditionResultDto(success=True))
        updates = UpdateConditionDto()
        updates.set("name", "Renamed Walls @B 8' - 0\"")
        result = service.update_condition(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            "12",
            updates,
        )
        self.assertTrue(result.success)
        self.assertEqual(
            events.published[0][1]["changed_fields"],
            ["is_top", "name", "z_value"],
        )

    def test_plain_condition_rename_remains_non_mesh_metadata(self):
        project_data = _ProjectData()
        project_data.conditions["12"] = Condition(uid="12", name="Walls @T 10' - 0\"")
        events = _EventBus()
        service, _, _, _ = _write_service(project_data, event_bus=events)
        service._update_condition = _UseCase(UpdateConditionResultDto(success=True))
        updates = UpdateConditionDto()
        updates.set("name", "Renamed Walls @T 10' - 0\"")
        result = service.update_condition(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            "12",
            updates,
        )
        self.assertTrue(result.success)
        self.assertEqual(events.published[0][1]["changed_fields"], ["name"])

    def test_locked_bid_expected_block_does_not_warn(self):
        project_data = _ProjectData()
        project_data.locked = True
        logger = logging.getLogger("tests.locked_bid_expected_block")
        guard = ActiveBidWriteGuard(project_data, logger)
        with self.assertNoLogs(logger, level="WARNING"):
            self.assertTrue(
                guard.blocks_active_locked_bid_write(
                    project_data.bid_ref.file_path,
                )
            )

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

    def test_write_service_rejects_incompatible_condition_reassignment_atomically(self):
        project_data = _ProjectData()
        project_data.conditions = {
            "linear": Condition(uid="linear", condition_type=Condition.TYPE_LINEAR),
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA),
        }
        linear_position = [0.0, 0.0, 10.0, 0.0]
        area_position = [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
        project_data.takeoffs = [
            Takeoff(
                uid="linear-takeoff",
                condition_uid="linear",
                position=list(linear_position),
            ),
            Takeoff(
                uid="area-takeoff",
                condition_uid="area",
                position=list(area_position),
            ),
        ]
        save_condition = _UseCase(True)
        service, *_ = _write_service(
            project_data,
            save_takeoffs_condition=save_condition,
        )
        rejected_requests = (
            (["linear-takeoff"], "area"),
            (["area-takeoff"], "linear"),
            (["linear-takeoff", "area-takeoff"], "linear"),
            (["missing"], "linear"),
        )
        with self.assertLogs(service.logger, level="WARNING") as captured:
            for takeoff_uids, target_uid in rejected_requests:
                with self.subTest(takeoff_uids=takeoff_uids, target_uid=target_uid):
                    self.assertFalse(
                        service.save_takeoffs_condition(
                            project_data.bid_ref.file_path,
                            takeoff_uids,
                            target_uid,
                            publish_database_refreshed_after_write=False,
                        )
                    )
            self.assertFalse(
                service.save_takeoffs_condition(
                    "C:/jobs/other.mdb",
                    ["linear-takeoff"],
                    "linear",
                    publish_database_refreshed_after_write=False,
                )
            )
        messages = "\n".join(captured.output)
        self.assertIn("Rejected incompatible", messages)
        self.assertIn("unknown takeoff", messages)
        self.assertIn("outside the active bid", messages)
        self.assertEqual(save_condition.calls, [])
        self.assertEqual(project_data.takeoffs[0].position, linear_position)
        self.assertEqual(project_data.takeoffs[1].position, area_position)
        self.assertEqual(project_data.takeoffs[0].condition_uid, "linear")
        self.assertEqual(project_data.takeoffs[1].condition_uid, "area")

    def test_write_service_allows_compatible_condition_reassignment(self):
        project_data = _ProjectData()
        project_data.conditions = {
            "linear-source": Condition(
                uid="linear-source", condition_type=Condition.TYPE_LINEAR
            ),
            "linear-target": Condition(
                uid="linear-target", condition_type=Condition.TYPE_LINEAR
            ),
        }
        project_data.takeoffs = [Takeoff(uid="takeoff", condition_uid="linear-source")]
        save_condition = _UseCase(True)
        service, *_ = _write_service(
            project_data,
            save_takeoffs_condition=save_condition,
        )
        result = service.save_takeoffs_condition(
            project_data.bid_ref.file_path,
            ["takeoff"],
            "linear-target",
            publish_database_refreshed_after_write=False,
        )
        self.assertTrue(result)
        self.assertEqual(
            save_condition.calls,
            [
                (
                    (
                        project_data.bid_ref.file_path,
                        ["takeoff"],
                        "linear-target",
                    ),
                    {},
                )
            ],
        )

    def _delete_project_data(
        self, selected_project_uid="project-2", remaining_uids=None
    ):
        remaining_uids = list(remaining_uids or [])
        projects = {
            selected_project_uid: HierarchyProjectInfo(
                name="Deleted Bids" if selected_project_uid == "1" else "Project",
                bids=[HierarchyBidInfo(uid=uid, name=uid) for uid in remaining_uids],
            )
        }
        if selected_project_uid != "1":
            projects["1"] = HierarchyProjectInfo(name="Deleted Bids")
        hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path="C:/jobs/test.mdb",
                    display_name="test.mdb",
                    bid_projects=projects,
                )
            ]
        )
        project_data = SimpleNamespace(
            clear_bid_calls=[],
            find_project_uid_for_bid=lambda _ref: selected_project_uid,
            get_hierarchy=lambda: hierarchy,
            get_current_file_path=lambda: "C:/jobs/test.mdb",
            project_exists=lambda project_uid, file_path: any(
                entry.file_path == file_path and project_uid in entry.bid_projects
                for entry in hierarchy.loaded_files
            ),
        )
        project_data.clear_bid = lambda: project_data.clear_bid_calls.append(True)
        return project_data

    def test_project_delete_identity_checks_are_scoped_to_database(self):
        project_uid = "shared-project"
        first_path = "C:/jobs/first.mdb"
        second_path = "C:/jobs/second.mdb"
        hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path=first_path,
                    bid_projects={
                        project_uid: HierarchyProjectInfo(
                            name="First",
                            bids=[HierarchyBidInfo(uid="bid-1")],
                        )
                    },
                ),
                HierarchyFileEntry(
                    file_path=second_path,
                    bid_projects={
                        project_uid: HierarchyProjectInfo(
                            name="Second",
                            bids=[],
                        )
                    },
                ),
            ]
        )
        project_data = ProjectDataService(
            SimpleNamespace(get_hierarchy_data=lambda: hierarchy)
        )
        delete_calls = []
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _database_id: False,
                delete_projects=lambda file_path, project_uids: delete_calls.append(
                    (file_path, list(project_uids))
                )
                or True,
            ),
            ui_state_manager=SimpleNamespace(),
            deferred_persistence_manager=_FakeDeferredPersistence(),
        )
        self.assertTrue(project_data.project_has_bids(project_uid, first_path))
        self.assertFalse(project_data.project_has_bids(project_uid, second_path))
        self.assertEqual(
            handler._valid_delete_selection_state(
                second_path,
                {
                    "kind": "project",
                    "file_path": second_path,
                    "project_uid": project_uid,
                },
            ),
            {
                "kind": "project",
                "file_path": second_path,
                "bid_uid": None,
                "project_uid": project_uid,
            },
        )
        with patch(
            "ost_visualizer.presentation.handlers.project_write_handler.confirm",
            return_value=True,
        ):
            handler._delete_projects([project_uid], second_path)
        self.assertEqual(delete_calls, [(second_path, [project_uid])])

    def test_moving_active_bid_to_deleted_clears_selection_before_refresh(self):
        bid_ref = BidRef("C:/jobs/test.mdb", "bid-1")
        ui_state = _DeleteBidUiState(bid_ref)
        project_data = self._delete_project_data(remaining_uids=[])
        write_service = _MoveToDeletedWriteService(ui_state)
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_FakeDeferredPersistence(),
        )
        from ost_visualizer.presentation.handlers import project_write_handler

        def confirm_yes(_window, _title, _message):
            return True

        old_confirm = project_write_handler.confirm
        project_write_handler.confirm = confirm_yes
        try:
            handler.delete_selected()
        finally:
            project_write_handler.confirm = old_confirm
        self.assertEqual(
            write_service.move_calls,
            [
                (
                    "C:/jobs/test.mdb",
                    ["bid-1"],
                    "1",
                    "project-2",
                    False,
                )
            ],
        )
        self.assertEqual(project_data.clear_bid_calls, [True])
        self.assertEqual(write_service.selected_bid_during_reload, [None])
        self.assertEqual(write_service.reloads, ["C:/jobs/test.mdb"])
        self.assertEqual(write_service.selected_bid_during_notify, [None])
        self.assertIsNone(ui_state.get_selected_bid_ref())
        self.assertEqual(write_service.notifications, ["C:/jobs/test.mdb"])

    def test_empty_project_delete_discards_selected_page_writes_before_flush(self):
        hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path="C:/jobs/test.mdb",
                    display_name="test.mdb",
                    bid_projects={
                        "project-empty": HierarchyProjectInfo(
                            name="Empty Project",
                            bids=[],
                        )
                    },
                )
            ]
        )
        project_data = SimpleNamespace(
            get_hierarchy=lambda: hierarchy,
            project_has_bids=lambda _project_uid, _file_path=None: False,
        )
        ui_state = SimpleNamespace(
            selected_project_uids=["project-empty"],
            selected_file_path="C:/jobs/test.mdb",
            get_selected_bid_refs=lambda: [],
        )
        delete_calls = []
        write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: False,
            delete_projects=lambda file_path, uids: delete_calls.append(
                (file_path, list(uids))
            )
            or True,
        )
        deferred = _DeferredPersistenceRequiringSelectedPageFileCancel(
            "C:/jobs/test.mdb"
        )
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=deferred,
        )
        from ost_visualizer.presentation.handlers import project_write_handler

        old_confirm = project_write_handler.confirm
        project_write_handler.confirm = lambda _window, _title, _message: True
        try:
            handler.delete_selected()
        finally:
            project_write_handler.confirm = old_confirm
        self.assertEqual(
            deferred.cancelled_bid_selected_page_files,
            ["C:/jobs/test.mdb"],
        )
        self.assertEqual(deferred.flushes, ["C:/jobs/test.mdb"])
        self.assertEqual(delete_calls, [("C:/jobs/test.mdb", ["project-empty"])])

    def test_moving_active_bid_to_deleted_selects_replacement_before_refresh(self):
        bid_ref = BidRef("C:/jobs/test.mdb", "bid-1")
        ui_state = _DeleteBidUiState(bid_ref)
        project_data = self._delete_project_data(remaining_uids=["bid-2"])
        write_service = _MoveToDeletedWriteService(ui_state)
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_FakeDeferredPersistence(),
        )
        from ost_visualizer.presentation.handlers import project_write_handler

        old_confirm = project_write_handler.confirm
        project_write_handler.confirm = lambda _window, _title, _message: True
        try:
            handler.delete_selected(
                {
                    "kind": "bid",
                    "file_path": "C:/jobs/test.mdb",
                    "bid_uid": "bid-2",
                    "project_uid": None,
                }
            )
        finally:
            project_write_handler.confirm = old_confirm
        replacement = ui_state.get_selected_bid_ref()
        self.assertIsNotNone(replacement)
        self.assertEqual(replacement.bid_uid, "bid-2")
        self.assertEqual(
            [
                ref.bid_uid if ref else None
                for ref in write_service.selected_bid_during_notify
            ],
            ["bid-2"],
        )

    def test_move_bid_to_deleted_discards_pending_selected_page_before_flush(self):
        bid_ref = BidRef("C:/jobs/test.mdb", "bid-1")
        ui_state = _DeleteBidUiState(bid_ref)
        project_data = self._delete_project_data(remaining_uids=[])
        write_service = _MoveToDeletedWriteService(ui_state)
        deferred = _DeferredPersistenceRequiringBidCancel("C:/jobs/test.mdb", "bid-1")
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=deferred,
        )
        from ost_visualizer.presentation.handlers import project_write_handler

        old_confirm = project_write_handler.confirm
        project_write_handler.confirm = lambda _window, _title, _message: True
        try:
            handler.delete_selected()
        finally:
            project_write_handler.confirm = old_confirm
        self.assertEqual(
            deferred.cancelled_bid_selected_pages,
            [("C:/jobs/test.mdb", ["bid-1"])],
        )
        self.assertEqual(deferred.flushes, ["C:/jobs/test.mdb"])
        self.assertEqual(
            write_service.move_calls,
            [("C:/jobs/test.mdb", ["bid-1"], "1", "project-2", False)],
        )

    def test_sql_bid_delete_completion_does_not_replace_newer_bid_selection(self):
        original = BidRef("C:/jobs/test.mdb", "bid-1")
        replacement = BidRef("C:/jobs/test.mdb", "bid-2")
        ui_state = _DeleteBidUiState(original)
        project_data = self._delete_project_data(remaining_uids=["bid-2"])
        write_service = _QueuedHierarchyDeleteWriteService()
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_FakeDeferredPersistence(),
        )
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: None,
                present_queued_mutation_error=lambda *_args: None,
            )
        )
        with patch(
            "ost_visualizer.presentation.handlers.project_write_handler.confirm",
            return_value=True,
        ):
            handler.delete_selected(
                {
                    "kind": "bid",
                    "file_path": original.file_path,
                    "bid_uid": replacement.bid_uid,
                    "project_uid": None,
                }
            )
        self.assertEqual(len(write_service.callbacks), 1)
        ui_state.set_bid_selection(replacement)
        write_service.callbacks[0](
            QueuedMutationResult(
                database_id=original.file_path,
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000101",
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(ui_state.get_selected_bid_ref(), replacement)
        self.assertEqual(project_data.clear_bid_calls, [])

    def test_sql_duplicate_completion_recomputes_current_toolbar_state(self):
        bid_ref = BidRef("C:/jobs/test.mdb", "bid-1")
        ui_state = _DeleteBidUiState(bid_ref)
        project_data = self._delete_project_data(remaining_uids=["bid-1"])
        write_service = _QueuedHierarchyDeleteWriteService()
        duplicate_action = _FakeAction()
        duplicate_action.setEnabled(True)
        refresh_calls = []

        def refresh_toolbar():
            refresh_calls.append(True)
            duplicate_action.setEnabled(False)

        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_FakeDeferredPersistence(),
        )
        handler.set_duplicate_action(duplicate_action)
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: None,
                present_queued_mutation_error=lambda *_args: None,
                refresh_toolbar=refresh_toolbar,
            )
        )
        handler.duplicate_selected()
        self.assertFalse(duplicate_action.isEnabled())
        write_service.callbacks[0](
            QueuedMutationResult(
                database_id=bid_ref.file_path,
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000105",
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(refresh_calls, [True])
        self.assertFalse(duplicate_action.isEnabled())

    def test_sql_bid_delete_completion_replaces_unchanged_deleted_selection(self):
        original = BidRef("C:/jobs/test.mdb", "bid-1")
        replacement = BidRef("C:/jobs/test.mdb", "bid-2")
        ui_state = _DeleteBidUiState(original)
        project_data = self._delete_project_data(remaining_uids=["bid-2"])
        write_service = _QueuedHierarchyDeleteWriteService()
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_FakeDeferredPersistence(),
        )
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: None,
                present_queued_mutation_error=lambda *_args: None,
            )
        )
        with patch(
            "ost_visualizer.presentation.handlers.project_write_handler.confirm",
            return_value=True,
        ):
            handler.delete_selected(
                {
                    "kind": "bid",
                    "file_path": original.file_path,
                    "bid_uid": replacement.bid_uid,
                    "project_uid": None,
                }
            )
        write_service.callbacks[0](
            QueuedMutationResult(
                database_id=original.file_path,
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000103",
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(ui_state.get_selected_bid_ref(), replacement)
        self.assertEqual(project_data.clear_bid_calls, [True])

    def test_sql_project_delete_completion_does_not_replace_newer_project_selection(
        self,
    ):
        file_path = "C:/jobs/test.mdb"
        hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path=file_path,
                    display_name="test.mdb",
                    bid_projects={
                        "project-delete": HierarchyProjectInfo(name="Delete", bids=[]),
                        "project-keep": HierarchyProjectInfo(name="Keep", bids=[]),
                    },
                )
            ]
        )
        project_data = SimpleNamespace(
            get_hierarchy=lambda: hierarchy,
            project_has_bids=lambda _project_uid, _file_path=None: False,
            project_exists=lambda project_uid, _file_path: project_uid
            in hierarchy.loaded_files[0].bid_projects,
        )
        ui_state = _DeleteBidUiState(BidRef(file_path, "unused"))
        ui_state.set_bid_selection(None)
        ui_state.set_file_path(file_path)
        ui_state.set_project_uid("project-delete")
        write_service = _QueuedHierarchyDeleteWriteService()
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_FakeDeferredPersistence(),
        )
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: None,
                present_queued_mutation_error=lambda *_args: None,
            )
        )
        with patch(
            "ost_visualizer.presentation.handlers.project_write_handler.confirm",
            return_value=True,
        ):
            handler.delete_selected()
        self.assertEqual(len(write_service.callbacks), 1)
        ui_state.set_project_uid("project-keep")
        write_service.callbacks[0](
            QueuedMutationResult(
                database_id=file_path,
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000102",
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(ui_state.selected_file_path, file_path)
        self.assertEqual(ui_state.selected_project_uid, "project-keep")

    def test_sql_project_delete_completion_clears_unchanged_deleted_selection(self):
        file_path = "C:/jobs/test.mdb"
        hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path=file_path,
                    display_name="test.mdb",
                    bid_projects={
                        "project-delete": HierarchyProjectInfo(name="Delete", bids=[])
                    },
                )
            ]
        )
        project_data = SimpleNamespace(
            get_hierarchy=lambda: hierarchy,
            project_has_bids=lambda _project_uid, _file_path=None: False,
            project_exists=lambda project_uid, _file_path: project_uid
            in hierarchy.loaded_files[0].bid_projects,
        )
        ui_state = _DeleteBidUiState(BidRef(file_path, "unused"))
        ui_state.set_bid_selection(None)
        ui_state.set_file_path(file_path)
        ui_state.set_project_uid("project-delete")
        write_service = _QueuedHierarchyDeleteWriteService()
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_FakeDeferredPersistence(),
        )
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: None,
                present_queued_mutation_error=lambda *_args: None,
            )
        )
        with patch(
            "ost_visualizer.presentation.handlers.project_write_handler.confirm",
            return_value=True,
        ):
            handler.delete_selected()
        write_service.callbacks[0](
            QueuedMutationResult(
                database_id=file_path,
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000104",
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(ui_state.selected_file_path, file_path)
        self.assertIsNone(ui_state.selected_project_uid)

    def test_permanently_deleting_active_deleted_bid_selects_replacement_before_refresh(
        self,
    ):
        bid_ref = BidRef("C:/jobs/test.mdb", "deleted-1")
        ui_state = _DeleteBidUiState(bid_ref)
        project_data = self._delete_project_data(
            selected_project_uid="1", remaining_uids=["deleted-2"]
        )
        write_service = _MoveToDeletedWriteService(ui_state)
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_FakeDeferredPersistence(),
        )
        from ost_visualizer.presentation.handlers import project_write_handler

        old_confirm = project_write_handler.confirm
        project_write_handler.confirm = lambda _window, _title, _message: True
        try:
            handler.delete_selected(
                {
                    "kind": "bid",
                    "file_path": "C:/jobs/test.mdb",
                    "bid_uid": "deleted-2",
                    "project_uid": None,
                }
            )
        finally:
            project_write_handler.confirm = old_confirm
        self.assertEqual(
            write_service.delete_calls,
            [("C:/jobs/test.mdb", ["deleted-1"], False)],
        )
        replacement = ui_state.get_selected_bid_ref()
        self.assertIsNotNone(replacement)
        self.assertEqual(replacement.bid_uid, "deleted-2")
        self.assertEqual(
            [
                ref.bid_uid if ref else None
                for ref in write_service.selected_bid_during_notify
            ],
            ["deleted-2"],
        )

    def test_permanent_bid_delete_discards_pending_selected_page_before_flush(self):
        bid_ref = BidRef("C:/jobs/test.mdb", "deleted-1")
        ui_state = _DeleteBidUiState(bid_ref)
        project_data = self._delete_project_data(
            selected_project_uid="1", remaining_uids=[]
        )
        write_service = _MoveToDeletedWriteService(ui_state)
        deferred = _DeferredPersistenceRequiringBidCancel(
            "C:/jobs/test.mdb", "deleted-1"
        )
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=deferred,
        )
        from ost_visualizer.presentation.handlers import project_write_handler

        old_confirm = project_write_handler.confirm
        project_write_handler.confirm = lambda _window, _title, _message: True
        try:
            handler.delete_selected()
        finally:
            project_write_handler.confirm = old_confirm
        self.assertEqual(
            deferred.cancelled_bid_selected_pages,
            [("C:/jobs/test.mdb", ["deleted-1"])],
        )
        self.assertEqual(deferred.flushes, ["C:/jobs/test.mdb"])
        self.assertEqual(
            write_service.delete_calls,
            [("C:/jobs/test.mdb", ["deleted-1"], False)],
        )

    def test_permanently_deleting_only_deleted_bid_falls_back_before_refresh(self):
        bid_ref = BidRef("C:/jobs/test.mdb", "deleted-1")
        ui_state = _DeleteBidUiState(bid_ref)
        project_data = self._delete_project_data(
            selected_project_uid="1", remaining_uids=[]
        )
        write_service = _MoveToDeletedWriteService(ui_state)
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_FakeDeferredPersistence(),
        )
        from ost_visualizer.presentation.handlers import project_write_handler

        old_confirm = project_write_handler.confirm
        project_write_handler.confirm = lambda _window, _title, _message: True
        try:
            handler.delete_selected(
                {
                    "kind": "project",
                    "file_path": "C:/jobs/test.mdb",
                    "bid_uid": None,
                    "project_uid": "1",
                }
            )
        finally:
            project_write_handler.confirm = old_confirm
        self.assertEqual(
            write_service.delete_calls,
            [("C:/jobs/test.mdb", ["deleted-1"], False)],
        )
        self.assertIsNone(ui_state.get_selected_bid_ref())
        self.assertEqual(ui_state.selected_project_uid, "1")
        self.assertEqual(ui_state.selected_file_path, "C:/jobs/test.mdb")
        self.assertEqual(write_service.selected_bid_during_notify, [None])

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

    def test_condition_create_result_keeps_uid_when_refresh_fails(self):
        project_data = _ProjectData()
        service, *_ = _write_service(project_data, reload_success=False)
        service._insert_condition = _UseCase("condition-new")
        result = service.create_condition_result(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            SimpleNamespace(),
        )
        self.assertFalse(result)
        self.assertTrue(result.write_success)
        self.assertTrue(result.refresh_failed)
        self.assertEqual(result.value, "condition-new")

    def test_condition_duplicate_result_keeps_uids_when_refresh_fails(self):
        project_data = _ProjectData()
        service, *_ = _write_service(project_data, reload_success=False)
        service._duplicate_conditions = _UseCase(["condition-copy"])
        result = service.duplicate_conditions_result(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            ["condition-1"],
        )
        self.assertFalse(result)
        self.assertTrue(result.write_success)
        self.assertTrue(result.refresh_failed)
        self.assertEqual(result.value, ["condition-copy"])

    def test_layer_insert_result_keeps_uid_when_refresh_fails(self):
        project_data = _ProjectData()
        service, *_ = _write_service(project_data, reload_success=False)
        service._insert_layer = _UseCase("layer-new")
        result = service.insert_layer_result(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            "Layer",
            1,
        )
        self.assertFalse(result)
        self.assertTrue(result.write_success)
        self.assertTrue(result.refresh_failed)
        self.assertEqual(result.value, "layer-new")

    def test_condition_type_save_result_keeps_mapping_when_refresh_fails(self):
        project_data = _ProjectData()
        service, *_ = _write_service(project_data, reload_success=False)
        service._save_condition_types = _SequenceUseCase(
            [{"new_condition_type": "type-new"}, {"new_condition_type": "type-legacy"}]
        )
        changes = {
            "new": [{"uid": "new_condition_type", "name": "Concrete"}],
            "updated": [],
            "deleted_uids": [],
        }
        result = service.save_condition_types_result(
            project_data.bid_ref.file_path, changes
        )
        self.assertFalse(result)
        self.assertTrue(result.write_success)
        self.assertTrue(result.refresh_failed)
        self.assertEqual(result.value, {"new_condition_type": "type-new"})
        self.assertIsNone(
            service.save_condition_types(project_data.bid_ref.file_path, changes)
        )

    def test_employee_save_result_keeps_mapping_when_refresh_fails(self):
        project_data = _ProjectData()
        service, *_ = _write_service(project_data, reload_success=False)
        service._save_employees = _SequenceUseCase([{"new_0": "employee-new"}])
        changes = {
            "new": [SimpleNamespace(uid="new_0")],
            "updated": [],
            "deleted_uids": [],
        }
        result = service.save_employees_result(project_data.bid_ref.file_path, changes)
        self.assertFalse(result)
        self.assertTrue(result.write_success)
        self.assertTrue(result.refresh_failed)
        self.assertEqual(result.value, {"new_0": "employee-new"})
        self.assertFalse(
            service.save_employees(project_data.bid_ref.file_path, changes)
        )

    def test_employee_save_result_can_skip_database_refresh(self):
        project_data = _ProjectData()
        service, *_ = _write_service(project_data)
        reload_calls = []
        service._reload_database = (
            lambda file_path: reload_calls.append(file_path) or True
        )
        service._save_employees = _UseCase({"new_0": "employee-new"})
        changes = {
            "new": [SimpleNamespace(uid="new_0")],
            "updated": [],
            "deleted_uids": [],
        }
        result = service.save_employees_result(
            project_data.bid_ref.file_path,
            changes,
            publish_database_refreshed_after_write=False,
        )
        self.assertTrue(result)
        self.assertEqual(result.value, {"new_0": "employee-new"})
        self.assertEqual(reload_calls, [])

    def test_condition_type_save_result_reports_write_failure(self):
        project_data = _ProjectData()
        service, *_ = _write_service(project_data)
        service._save_condition_types = _SequenceUseCase([None])
        changes = {"new": [], "updated": [], "deleted_uids": ["type-used"]}
        result = service.save_condition_types_result(
            project_data.bid_ref.file_path, changes
        )
        self.assertFalse(result)
        self.assertFalse(result.write_success)
        self.assertFalse(result.reload_success)
        self.assertIsNone(result.value)

    def test_condition_type_save_result_can_skip_database_refresh(self):
        project_data = _ProjectData()
        service, *_ = _write_service(project_data)
        reload_calls = []
        service._reload_database = (
            lambda file_path: reload_calls.append(file_path) or True
        )
        service._save_condition_types = _UseCase({"new_condition_type": "type-new"})
        changes = {
            "new": [{"uid": "new_condition_type", "name": "Concrete"}],
            "updated": [],
            "deleted_uids": [],
        }
        result = service.save_condition_types_result(
            project_data.bid_ref.file_path,
            changes,
            publish_database_refreshed_after_write=False,
        )
        self.assertTrue(result)
        self.assertEqual(result.value, {"new_condition_type": "type-new"})
        self.assertEqual(reload_calls, [])

    def test_mdb_condition_type_save_refreshes_sidebar_without_database_event(self):
        project_data = _ProjectData()
        events = _EventBus()
        service, *_ = _write_service(project_data, event_bus=events)
        service._save_condition_types = _UseCase({"new_condition_type": "type-new"})
        changes = {
            "new": [{"uid": "new_condition_type", "name": "Concrete"}],
            "updated": [],
            "deleted_uids": [],
        }
        result = service.save_condition_types_result(
            project_data.bid_ref.file_path,
            changes,
        )
        self.assertTrue(result)
        self.assertEqual(
            events.published,
            [
                (
                    AppEvents.CONDITIONS_CHANGED,
                    {
                        "database_id": project_data.bid_ref.file_path,
                        "bid_uid": project_data.bid_ref.bid_uid,
                        "condition_uids": [],
                        "changed_fields": ["condition_type_catalog"],
                        "change_operations": [],
                        "invalidates_undo": False,
                    },
                )
            ],
        )

    def test_condition_folder_delete_result_blocks_in_use_folder(self):
        project_data = _ProjectData()
        service, *_ = _write_service(project_data)
        service._project_data = SimpleNamespace(
            get_bid_condition_folders=lambda: {
                "folder-1": SimpleNamespace(parent_uid=None)
            },
            get_bid_conditions=lambda: {
                "cond-1": SimpleNamespace(folder_uid="folder-1")
            },
        )
        delete_use_case = _UseCase(True)
        service._delete_condition_folders = delete_use_case
        result = service.delete_condition_folders_result(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            ["folder-1"],
        )
        self.assertFalse(result)
        self.assertFalse(result.write_success)
        self.assertEqual(result.failure_reason, "condition_folder_in_use")
        self.assertEqual(result.blocked_uids, ["folder-1"])
        self.assertEqual(delete_use_case.calls, [])

    def test_condition_folder_delete_result_allows_unused_folder(self):
        project_data = _ProjectData()
        service, *_ = _write_service(project_data)
        service._project_data = SimpleNamespace(
            get_bid_condition_folders=lambda: {
                "folder-1": SimpleNamespace(parent_uid=None)
            },
            get_bid_conditions=lambda: {},
        )
        delete_use_case = _UseCase(True)
        service._delete_condition_folders = delete_use_case
        result = service.delete_condition_folders_result(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            ["folder-1"],
        )
        self.assertTrue(result)
        self.assertEqual(result.value, ["folder-1"])
        self.assertEqual(
            delete_use_case.calls,
            [((project_data.bid_ref.file_path, ["folder-1"]), {})],
        )

    def test_condition_type_delete_result_blocks_in_use_type(self):
        project_data = _ProjectData()
        service, *_ = _write_service(project_data)
        service._condition_type_uids_in_use_provider = lambda _file_path: {"type-used"}
        save_use_case = _SequenceUseCase([{}])
        service._save_condition_types = save_use_case
        result = service.delete_condition_types_result(
            project_data.bid_ref.file_path, ["type-used"]
        )
        self.assertFalse(result)
        self.assertFalse(result.write_success)
        self.assertEqual(result.failure_reason, "condition_type_in_use")
        self.assertEqual(result.blocked_uids, ["type-used"])
        self.assertEqual(save_use_case.calls, [])

    def test_condition_type_delete_result_allows_unused_type(self):
        project_data = _ProjectData()
        service, *_ = _write_service(project_data)
        service._condition_type_uids_in_use_provider = lambda _file_path: {"type-used"}
        save_use_case = _SequenceUseCase([{}])
        service._save_condition_types = save_use_case
        result = service.delete_condition_types_result(
            project_data.bid_ref.file_path, ["type-unused"]
        )
        self.assertTrue(result)
        self.assertEqual(
            save_use_case.calls,
            [
                (
                    (
                        project_data.bid_ref.file_path,
                        {
                            "new": [],
                            "updated": [],
                            "deleted_uids": ["type-unused"],
                        },
                    ),
                    {},
                )
            ],
        )

    def test_condition_type_delete_fails_closed_when_usage_is_unavailable(self):
        project_data = _ProjectData()
        for provider in (
            None,
            lambda _file_path: (_ for _ in ()).throw(RuntimeError("read failed")),
        ):
            with self.subTest(provider=provider):
                service, *_ = _write_service(project_data)
                service._condition_type_uids_in_use_provider = provider
                save_use_case = _SequenceUseCase([{}])
                service._save_condition_types = save_use_case
                result = service.delete_condition_types_result(
                    project_data.bid_ref.file_path, ["type-unknown"]
                )
                self.assertFalse(result)
                self.assertFalse(result.write_success)
                self.assertEqual(
                    result.failure_reason, "condition_type_usage_unavailable"
                )
                self.assertEqual(result.blocked_uids, ["type-unknown"])
                self.assertEqual(save_use_case.calls, [])

    def test_delete_pages_normalizes_empty_and_duplicate_uids(self):
        project_data = _ProjectData()
        service, *_ = _write_service(project_data)
        delete_use_case = _UseCase(True)
        service._delete_pages = delete_use_case
        self.assertTrue(
            service.delete_pages(
                project_data.bid_ref.file_path,
                ["page-1", "", "page-1", "page-2"],
            )
        )
        self.assertEqual(
            delete_use_case.calls,
            [
                (
                    (
                        project_data.bid_ref.file_path,
                        ["page-1", "page-2"],
                    ),
                    {},
                )
            ],
        )

    def test_condition_folder_delete_handler_uses_shared_validation(self):
        access = _FakeAccess({Feature.EDIT_CONDITION_STRUCTURE})
        validate_calls = []
        delete_calls = []

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return False

            def validate_condition_folder_delete(self, file_path, bid_uid, folder_uids):
                validate_calls.append((file_path, bid_uid, list(folder_uids)))
                return DeleteValidationResult(
                    requested_uids=list(folder_uids),
                    blocked_uids=["folder-1"],
                    failure_reason="condition_folder_in_use",
                )

            def delete_condition_folders_result(self, db_path, bid_uid, folder_uids):
                delete_calls.append((db_path, bid_uid, folder_uids))
                raise AssertionError("blocked folder delete should not run")

        coordinator = SimpleNamespace(
            ui_access_manager=access,
            conditions_sidebar=SimpleNamespace(window=lambda: None),
            flush_deferred_for_file=lambda _file_path: True,
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=WriteService(),
            project_read_service=None,
            project_data=SimpleNamespace(
                get_bid_condition_folders=lambda: {
                    "folder-1": SimpleNamespace(name="Folder 1")
                }
            ),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: BidRef("db.mdb", "bid-1")
            ),
            workspace_state_model=make_workspace_state_model(),
        )
        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "confirm_multi_delete",
            return_value=None,
        ) as confirm_delete:
            handler.on_folder_delete_requested(["folder-1"])
        self.assertEqual(validate_calls, [("db.mdb", "bid-1", ["folder-1"])])
        self.assertEqual(delete_calls, [])
        self.assertEqual(confirm_delete.call_args.args[3], {"folder-1"})

    def test_condition_dialog_layer_insert_warns_when_refresh_fails(self):
        warnings = []
        bid_ref = BidRef("db.mdb", "bid-1")
        coordinator = SimpleNamespace(
            conditions_sidebar=None,
            flush_deferred_for_file=lambda _file_path: True,
        )
        write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: False,
            insert_layer_result=lambda _file_path, _bid_uid, _name, _sequence: (
                WriteReloadResult("layer-new", write_success=True, reload_success=False)
            ),
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=write_service,
            project_read_service=None,
            project_data=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(),
            workspace_state_model=make_workspace_state_model(),
        )
        from ost_visualizer.presentation.handlers import condition_action_handler

        old_warning = condition_action_handler.show_warning
        condition_action_handler.show_warning = lambda *args: warnings.append(args)
        try:
            callbacks = handler._layer_dialog_callbacks(bid_ref, write_service)
            uid = callbacks["layer_insert_fn"]("Layer", 3)
        finally:
            condition_action_handler.show_warning = old_warning
        self.assertEqual(uid, "layer-new")
        self.assertEqual(len(warnings), 1)
        self.assertIn(
            "created, but the layer list could not be refreshed", warnings[0][2]
        )

    def test_condition_dialog_condition_type_save_warns_when_refresh_fails(self):
        warnings = []
        bid_ref = BidRef("db.mdb", "bid-1")
        coordinator = SimpleNamespace(
            conditions_sidebar=None,
            flush_deferred_for_file=lambda _file_path: True,
        )
        write_service = SimpleNamespace(
            save_condition_types_result=lambda _file_path, _changes: (
                WriteReloadResult(
                    {"new_condition_type": "type-new"},
                    write_success=True,
                    reload_success=False,
                )
            )
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=write_service,
            project_read_service=None,
            project_data=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(),
            workspace_state_model=make_workspace_state_model(),
        )
        from ost_visualizer.presentation.handlers import condition_action_handler

        old_warning = condition_action_handler.show_warning
        condition_action_handler.show_warning = lambda *args: warnings.append(args)
        try:
            result = handler._save_condition_types_from_dialog(
                bid_ref,
                write_service,
                {"new": [{"uid": "new_condition_type", "name": "Concrete"}]},
            )
        finally:
            condition_action_handler.show_warning = old_warning
        self.assertEqual(result, {"new_condition_type": "type-new"})
        self.assertEqual(len(warnings), 1)
        self.assertIn("could not be refreshed", warnings[0][2])

    def test_new_folder_warns_when_create_succeeds_but_refresh_fails(self):
        warnings = []
        criticals = []
        renames = []
        controller = MenuController.__new__(MenuController)
        controller.window = SimpleNamespace(
            project_view=SimpleNamespace(
                schedule_rename=lambda uid, file_path: renames.append((uid, file_path))
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
        controller._deferred_persistence = _FakeDeferredPersistence()
        controller._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: False,
            create_project_result=lambda _path, _name: WriteReloadResult(
                "project-new", write_success=True, reload_success=False
            ),
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

    def test_new_folder_schedules_rename_with_target_database(self):
        renames = []
        controller = MenuController.__new__(MenuController)
        controller.window = SimpleNamespace(
            project_view=SimpleNamespace(
                schedule_rename=lambda uid, file_path: renames.append((uid, file_path))
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
        controller._deferred_persistence = _FakeDeferredPersistence()
        controller._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: False,
            create_project_result=lambda _path, _name: WriteReloadResult(
                "project-new", write_success=True, reload_success=True
            ),
        )
        MenuController._new_folder(controller)
        self.assertEqual(renames, [("project-new", "db.mdb")])

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

    def test_save_bid_areas_result_preserves_uid_map_when_refresh_fails(self):
        project_data = _ProjectData()
        service, *_ = _write_service(project_data, reload_success=False)
        service._save_bid_areas = _UseCase({"new_0": "area-2"})
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
        result = service.save_bid_areas_result(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            changes,
        )
        self.assertTrue(result.write_success)
        self.assertTrue(result.refresh_failed)
        self.assertEqual(result.value, {"new_0": "area-2"})
        self.assertIsNone(
            service.save_bid_areas(
                project_data.bid_ref.file_path,
                project_data.bid_ref.bid_uid,
                changes,
            )
        )

    def test_save_bid_areas_result_can_skip_database_refresh(self):
        project_data = _ProjectData()
        service, *_ = _write_service(project_data)
        reload_calls = []
        service._reload_database = (
            lambda file_path: reload_calls.append(file_path) or True
        )
        service._save_bid_areas = _UseCase({"new_0": "area-2"})
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
        result = service.save_bid_areas_result(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            changes,
            publish_database_refreshed_after_write=False,
        )
        self.assertTrue(result)
        self.assertEqual(result.value, {"new_0": "area-2"})
        self.assertEqual(reload_calls, [])


if __name__ == "__main__":
    unittest.main()
