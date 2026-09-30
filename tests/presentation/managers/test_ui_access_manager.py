import unittest
from types import SimpleNamespace
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    DatabaseMutationResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceRef,
    SynchronizationConflict,
    SynchronizationConflictKind,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
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
    _License as _permissions__License,
    _UiState as _permissions__UiState,
)
from dataclasses import replace
from ost_visualizer.application.dtos.collaboration_dtos import ResourceRef
from ost_visualizer.presentation.managers.ui_access_manager import (
    MAIN_PLAN_SURFACE_ID,
    PlanSurfaceAccessContext,
    PlanSurfaceAccessState,
    UIAccessManager,
)
from tests.presentation.managers.surface_access_support import (
    _Capabilities as _surface_access_support__Capabilities,
    _EventBus as _surface_access_support__EventBus,
    _License as _surface_access_support__License,
    _ProjectData as _surface_access_support__ProjectData,
    _TransactionMonitor as _surface_access_support__TransactionMonitor,
    _UiState as _surface_access_support__UiState,
)


class BidLockPermissionTests(unittest.TestCase):
    def test_ui_access_constructor_rolls_back_subscriptions_when_refresh_fails(self):
        event_bus = _permissions__EventBus()

        class FailingTransactionMonitor:
            def is_ost_active(self):
                raise RuntimeError("OST status unavailable")

        with self.assertRaisesRegex(RuntimeError, "OST status unavailable"):
            UIAccessManager(
                event_bus,
                _permissions__License(),
                FailingTransactionMonitor(),
                SimpleNamespace(),
                SimpleNamespace(),
                _permissions__DatabaseCapability(),
            )
        self.assertEqual(event_bus.subscriptions, [])

    def test_ui_access_cleanup_retries_only_failed_unsubscriptions(self):
        class TransientEventBus(_permissions__EventBus):
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
            _permissions__License(),
            _permissions__TransactionMonitor(),
            _permissions__ProjectData(),
            _permissions__UiState(BidRef("test.mdb", "bid-1")),
            _permissions__DatabaseCapability(),
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

    def _access_manager(self, project_data, ui_state=None, capability=None):
        return UIAccessManager(
            _permissions__EventBus(),
            _permissions__License(),
            _permissions__TransactionMonitor(),
            project_data,
            ui_state or _permissions__UiState(project_data.bid_ref),
            capability or _permissions__DatabaseCapability(),
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
        project_data = _permissions__ProjectData()
        manager = self._access_manager(
            project_data, capability=_permissions__DatabaseCapability(editable=False)
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
        project_data = _permissions__ProjectData()
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

    def test_context_duplicate_permission_uses_captured_bid_database_and_resource(self):
        project_data = _permissions__ProjectData()
        checks = []

        class _TargetCapability:
            def is_editable(self, locator, resource=None):
                checks.append((locator, resource))
                return locator == "C:/jobs/target.mdb"

        manager = self._access_manager(
            project_data,
            capability=_TargetCapability(),
        )
        target = BidRef("C:/jobs/target.mdb", "9")
        self.assertTrue(manager.can_duplicate_bid(target))
        self.assertEqual(
            checks,
            [("C:/jobs/target.mdb", ResourceRef("bid", "9", 9))],
        )

    def test_unknown_feature_and_edit_without_database_are_denied(self):
        project_data = _permissions__ProjectData()
        manager = self._access_manager(project_data)
        self.assertFalse(manager.is_allowed(object()))
        manager._ui_state_manager.selected_file_path = None
        self.assertFalse(manager.is_allowed(Feature.EDIT_PLAN_ITEMS))

    def test_bid_lock_applies_and_unlocks_immediately_in_access_manager(self):
        project_data = _permissions__ProjectData()
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
        project_data = _permissions__ProjectData()
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
        project_data = _permissions__ProjectData()
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
        project_data = _permissions__ProjectData()
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

    def test_text_annotation_edit_mode_blocks_conflicting_actions(self):
        project_data = _permissions__ProjectData()
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


class PlanSurfaceAccessTests(unittest.TestCase):
    def setUp(self):
        self.bid_ref = BidRef("project.mdb", "7")
        self.events = _surface_access_support__EventBus()
        self.license = _surface_access_support__License()
        self.transaction = _surface_access_support__TransactionMonitor()
        self.project = _surface_access_support__ProjectData(self.bid_ref)
        self.ui_state = _surface_access_support__UiState(self.bid_ref)
        self.capabilities = _surface_access_support__Capabilities()
        self.manager = UIAccessManager(
            self.events,
            self.license,
            self.transaction,
            self.project,
            self.ui_state,
            self.capabilities,
        )

    def tearDown(self):
        self.manager.cleanup()

    def _context(
        self,
        page_uid,
        *,
        surface_id="main-plan",
        bid_ref=None,
        database_id="project.mdb",
        layer_visible=True,
    ):
        return PlanSurfaceAccessContext(
            surface_id=surface_id,
            database_id=database_id,
            bid_ref=self.bid_ref if bid_ref is None else bid_ref,
            page_uid=page_uid,
            annotation_layer_visible=layer_visible,
        )

    def test_page_locks_are_evaluated_against_each_displayed_page(self):
        self.capabilities.locked_pages = {"page-b"}
        main = self.manager.get_plan_surface_access(self._context("page-a"))
        detached = self.manager.get_plan_surface_access(
            self._context("page-b", surface_id="detached-plan")
        )
        self.assertTrue(main.can_edit_page_settings)
        self.assertFalse(detached.can_edit_page_settings)
        self.assertTrue(main.can_place_annotations)
        self.assertTrue(detached.can_place_annotations)
        self.assertIn(
            (
                "project.mdb",
                ResourceRef("page", "page-b", 7),
            ),
            self.capabilities.requests,
        )

    def test_editable_detached_page_is_not_disabled_by_locked_main_page(self):
        self.capabilities.locked_pages = {"page-a"}
        main = self.manager.get_plan_surface_access(self._context("page-a"))
        detached = self.manager.get_plan_surface_access(
            self._context("page-b", surface_id="detached-plan")
        )
        self.assertFalse(main.can_edit_page_settings)
        self.assertTrue(detached.can_edit_page_settings)
        self.assertTrue(detached.can_place_annotations)

    def test_target_page_change_recalculates_page_resource(self):
        self.capabilities.locked_pages = {"page-b"}
        editable = self.manager.get_plan_surface_access(
            self._context("page-a", surface_id="detached-plan")
        )
        locked = self.manager.get_plan_surface_access(
            self._context("page-b", surface_id="detached-plan")
        )
        self.assertTrue(editable.can_edit_page_settings)
        self.assertFalse(locked.can_edit_page_settings)

    def test_missing_or_inconsistent_context_fails_closed(self):
        context = self._context("page-a", surface_id="detached-plan")
        invalid_contexts = (
            replace(context, surface_id=""),
            replace(context, database_id=""),
            replace(context, bid_ref=None),
            replace(context, page_uid=""),
            replace(context, database_id="other.mdb"),
            replace(context, bid_ref=BidRef("project.mdb", "8")),
        )
        requests_before = list(self.capabilities.requests)
        for invalid_context in invalid_contexts:
            with self.subTest(context=invalid_context):
                self.assertEqual(
                    self.manager.get_plan_surface_access(invalid_context),
                    PlanSurfaceAccessState(),
                )
        self.assertEqual(self.capabilities.requests, requests_before)

    def test_page_settings_lock_does_not_disable_annotation_capabilities(self):
        self.capabilities.locked_pages = {"page-a"}
        state = self.manager.get_plan_surface_access(self._context("page-a"))
        self.assertFalse(state.can_edit_page_settings)
        self.assertTrue(state.can_place_annotations)
        self.assertTrue(state.can_edit_annotations)
        self.assertTrue(state.can_edit_annotation_text)

    def test_hidden_annotation_layer_blocks_placement_not_other_mutations(self):
        state = self.manager.get_plan_surface_access(
            self._context("page-a", layer_visible=False)
        )
        self.assertFalse(state.can_place_annotations)
        self.assertTrue(state.can_edit_annotations)
        self.assertTrue(state.can_edit_annotation_text)
        self.assertTrue(state.can_edit_page_settings)

    def test_same_context_produces_same_main_and_detached_annotation_state(self):
        main = self.manager.get_plan_surface_access(
            self._context("page-a", surface_id="main-plan")
        )
        detached = self.manager.get_plan_surface_access(
            self._context("page-a", surface_id="detached-plan")
        )
        self.assertEqual(
            (
                main.can_place_annotations,
                main.can_edit_annotations,
                main.can_edit_annotation_text,
            ),
            (
                detached.can_place_annotations,
                detached.can_edit_annotations,
                detached.can_edit_annotation_text,
            ),
        )

    def test_surface_area_placement_preserves_only_its_own_continuation(self):
        self.manager.set_area_placement_active(True, surface_id="detached-plan")
        detached = self.manager.get_plan_surface_access(
            self._context("page-a", surface_id="detached-plan")
        )
        main = self.manager.get_plan_surface_access(
            self._context("page-a", surface_id="main-plan")
        )
        self.assertFalse(detached.can_place_annotations)
        self.assertTrue(detached.can_continue_annotation_placement)
        self.assertFalse(detached.can_edit_annotations)
        self.assertFalse(main.can_place_annotations)
        self.assertFalse(main.can_continue_annotation_placement)

    def test_one_surface_ending_does_not_clear_another_surface_blocker(self):
        self.manager.set_area_placement_active(True, surface_id=MAIN_PLAN_SURFACE_ID)
        self.manager.set_area_placement_active(True, surface_id="detached-plan")
        self.manager.clear_plan_surface_interaction("detached-plan")
        detached = self.manager.get_plan_surface_access(
            self._context("page-a", surface_id="detached-plan")
        )
        self.assertFalse(detached.can_continue_annotation_placement)

    def test_inline_text_edit_preserves_text_capability_only(self):
        self.manager.set_text_annotation_edit_active(True, surface_id="detached-plan")
        state = self.manager.get_plan_surface_access(
            self._context("page-a", surface_id="detached-plan")
        )
        self.assertFalse(state.can_place_annotations)
        self.assertFalse(state.can_edit_annotations)
        self.assertTrue(state.can_edit_annotation_text)
        self.assertFalse(state.can_edit_page_settings)

    def test_access_sources_notify_listeners_once_per_logical_change(self):
        calls = []
        self.manager.subscribe_access_state_changed(lambda: calls.append("refresh"))
        self.license.valid = False
        self.events.publish(AppEvents.LICENSE_EXPIRED)
        self.assertEqual(calls, [])
        self.events.publish(AppEvents.LICENSE_STATUS_CHANGED)
        self.assertEqual(calls, ["refresh"])
        self.transaction.active = True
        self.events.publish(AppEvents.OST_STATUS_CHANGED, active=True)
        self.assertEqual(calls, ["refresh", "refresh"])
        self.manager.refresh()
        self.assertEqual(calls, ["refresh", "refresh", "refresh"])
        self.manager.set_area_placement_active(True, surface_id=MAIN_PLAN_SURFACE_ID)
        self.assertEqual(len(calls), 4)
        self.manager.set_area_placement_active(True, surface_id=MAIN_PLAN_SURFACE_ID)
        self.assertEqual(len(calls), 4)
        self.manager.set_text_annotation_edit_active(True, surface_id="detached-plan")
        self.assertEqual(len(calls), 5)
        state = self.manager.get_plan_surface_access(self._context("page-a"))
        self.assertFalse(state.can_place_annotations)

    def test_inactive_surface_interactions_are_not_cached(self):
        self.manager.set_area_placement_active(True, surface_id="detached-plan")
        self.manager.set_area_placement_active(False, surface_id="detached-plan")
        self.assertNotIn("detached-plan", self.manager._surface_interactions)
