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
    _LOCK_BLOCKED,
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

    def test_ui_access_constructor_reports_refresh_and_cleanup_failures_together(self):
        class FailingEventBus(_permissions__EventBus):
            def unsubscribe(self, event_type, callback):
                raise RuntimeError("unsubscribe unavailable")

        class FailingTransactionMonitor:
            def is_ost_active(self):
                raise RuntimeError("OST status unavailable")

        with self.assertRaises(ExceptionGroup) as raised:
            UIAccessManager(
                FailingEventBus(),
                _permissions__License(),
                FailingTransactionMonitor(),
                SimpleNamespace(),
                SimpleNamespace(),
                _permissions__DatabaseCapability(),
            )
        self.assertEqual(
            str(raised.exception),
            "UI access initialization and cleanup failed (2 sub-exceptions)",
        )
        initialization_error, cleanup_error = raised.exception.exceptions
        self.assertEqual(str(initialization_error), "OST status unavailable")
        self.assertIsInstance(cleanup_error, ExceptionGroup)
        self.assertIs(raised.exception.__cause__, initialization_error)

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
        self.assertEqual(
            [event_type for event_type, _callback in event_bus.subscriptions],
            [AppEvents.LICENSE_STATUS_CHANGED],
        )
        self.assertIs(manager._event_bus, event_bus)
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
        for feature in _DATABASE_EDIT_FEATURES - {Feature.CREATE_DATABASE}:
            with self.subTest(feature=feature):
                self.assertFalse(manager.is_allowed(feature))
        self.assertTrue(manager.is_allowed(Feature.CREATE_DATABASE))
        self.assertTrue(manager.is_allowed(Feature.UNLOAD_FILE))

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
        checks.clear()
        other = BidRef("C:/jobs/other.mdb", "9")
        self.assertFalse(manager.can_duplicate_bid(other))
        self.assertEqual(
            checks,
            [("C:/jobs/other.mdb", ResourceRef("bid", "9", 9))],
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
        # Decision H1: the Condition folder commands (create/rename/delete folder,
        # cut/paste-move, drag-move) are writes the service guard already rejects on a
        # locked active Bid, so the UI permission blocks them as well.
        self.assertFalse(manager.is_allowed(Feature.EDIT_CONDITION_STRUCTURE))
        self.assertFalse(manager.is_allowed(Feature.EDIT_CONDITION))
        self.assertFalse(manager.is_allowed(Feature.SELECT_PLAN_ITEMS))
        self.assertFalse(manager.is_allowed(Feature.PLACE_PLAN_ITEMS))
        self.assertFalse(manager.is_allowed(Feature.EDIT_ANNOTATION_TEXT))
        self.assertTrue(manager.is_allowed(Feature.DELETE_BID))
        self.assertTrue(manager.is_allowed(Feature.DUPLICATE_BID))
        self.assertTrue(manager.is_allowed(Feature.EDIT_BID_JOB_STATUS))
        self.assertTrue(manager.is_allowed(Feature.COPY_CONDITION))
        self.assertTrue(manager.is_allowed(Feature.COPY_BID))
        project_data.locked = False
        self.assertTrue(manager.is_allowed(Feature.EDIT_PROJECT_TREE_STRUCTURE))
        self.assertTrue(manager.is_allowed(Feature.EDIT_CONDITION_STRUCTURE))
        self.assertTrue(manager.is_allowed(Feature.EDIT_CONDITION))
        self.assertTrue(manager.is_allowed(Feature.SELECT_PLAN_ITEMS))
        self.assertTrue(manager.is_allowed(Feature.PLACE_PLAN_ITEMS))
        self.assertTrue(manager.is_allowed(Feature.DELETE_BID))
        self.assertTrue(manager.is_allowed(Feature.DUPLICATE_BID))

    def test_bid_lock_blocks_condition_structure_writes_but_not_read_only_features(
        self,
    ):
        project_data = _permissions__ProjectData()
        manager = self._access_manager(project_data)
        read_only_features = (
            Feature.COPY_CONDITION,
            Feature.COPY_BID,
            Feature.EXPORT,
            Feature.EXPORT_BID_FILE,
            Feature.VIEW_2D,
            Feature.VIEW_3D,
            Feature.UNLOAD_FILE,
        )
        self.assertTrue(manager.is_allowed(Feature.EDIT_CONDITION_STRUCTURE))
        for feature in read_only_features:
            with self.subTest(unlocked=feature):
                self.assertTrue(manager.is_allowed(feature))
        project_data.locked = True
        self.assertFalse(manager.is_allowed(Feature.EDIT_CONDITION_STRUCTURE))
        self.assertFalse(
            manager.is_allowed(
                Feature.EDIT_CONDITION_STRUCTURE,
                ResourceRef(
                    "conditions_collection",
                    str(project_data.bid_ref.bid_uid),
                    int(project_data.bid_ref.bid_uid),
                ),
            )
        )
        for feature in read_only_features:
            with self.subTest(locked=feature):
                self.assertTrue(manager.is_allowed(feature))
        project_data.locked = False
        self.assertTrue(manager.is_allowed(Feature.EDIT_CONDITION_STRUCTURE))

    def test_condition_structure_permission_matrix_by_role_is_unchanged_by_lock(self):
        # Editor (editable database) is blocked only by the lock; viewer (read-only
        # database) is blocked locked or not; the lock never grants anything.
        for editable, locked, expected in (
            (True, False, True),
            (True, True, False),
            (False, False, False),
            (False, True, False),
        ):
            with self.subTest(editable=editable, locked=locked):
                project_data = _permissions__ProjectData()
                project_data.locked = locked
                manager = self._access_manager(
                    project_data,
                    capability=_permissions__DatabaseCapability(editable=editable),
                )
                self.assertEqual(
                    manager.is_allowed(Feature.EDIT_CONDITION_STRUCTURE), expected
                )
                self.assertEqual(manager.is_allowed(Feature.COPY_CONDITION), True)

    def test_lock_blocked_features_are_bid_contents_never_project_tree_structure(self):
        # Decision P4: the Bid status lock covers the Bid's own contents; project-level
        # structure (projects, folders, Bid placement) is not in the lock set.
        self.assertEqual(
            _LOCK_BLOCKED,
            frozenset(
                {
                    Feature.EDIT_CONDITION_STRUCTURE,
                    Feature.EDIT_PAGE_SETTINGS,
                    Feature.SELECT_PLAN_ITEMS,
                    Feature.EDIT_PLAN_ITEMS,
                    Feature.PLACE_PLAN_ITEMS,
                    Feature.PLACE_ANNOTATIONS,
                    Feature.DUPLICATE_CONDITION,
                    Feature.DELETE_CONDITION,
                    Feature.EDIT_CONDITION,
                    Feature.EDIT_ANNOTATION_TEXT,
                }
            ),
        )
        self.assertNotIn(Feature.EDIT_PROJECT_TREE_STRUCTURE, _LOCK_BLOCKED)

    def test_project_tree_structure_permission_matrix_by_role_is_unchanged_by_lock(
        self,
    ):
        # Decision P4: every project-level use of EDIT_PROJECT_TREE_STRUCTURE (menu New
        # Project/Folder, New Bid, drag-move/restore Bids, rename/delete project,
        # database maintenance) is decided by the database role only. Editor: allowed
        # locked or not; viewer: denied locked or not; the lock never changes it.
        # Decision Q1 changes the contract for exactly three rows: moving/restoring,
        # trashing and deleting the project of the ACTIVE locked Bid itself are also
        # denied for an editor while it is locked (checked after the role matrix).
        for editable, locked in (
            (True, False),
            (True, True),
            (False, False),
            (False, True),
        ):
            with self.subTest(editable=editable, locked=locked):
                project_data = _permissions__ProjectData()
                project_data.locked = locked
                manager = self._access_manager(
                    project_data,
                    capability=_permissions__DatabaseCapability(editable=editable),
                )
                database_id = project_data.bid_ref.file_path
                decisions = {
                    "is_allowed": manager.is_allowed(
                        Feature.EDIT_PROJECT_TREE_STRUCTURE
                    ),
                    "can_create_project_tree_items": (
                        manager.can_create_project_tree_items(True)
                    ),
                    "can_create_bid_in_project": manager.can_create_bid(
                        database_id, "project-1"
                    ),
                    "can_create_bid_orphan": manager.can_create_bid(database_id, None),
                    "can_create_project": manager.can_create_project(database_id),
                    "can_edit_bid_structure": manager.can_edit_bid_structure(
                        [BidRef(database_id, "8")]
                    ),
                    "can_edit_project": manager.can_edit_project(database_id, "2"),
                    "can_delete_projects": manager.can_delete_projects(
                        database_id, ["2"]
                    ),
                    "can_maintain_database": manager.can_maintain_database(database_id),
                }
                self.assertEqual(decisions, {name: editable for name in decisions})
                active_bid_rows = {
                    "can_edit_bid_structure": manager.can_edit_bid_structure(
                        [project_data.bid_ref]
                    ),
                    "can_delete_bids": manager.can_delete_bids([project_data.bid_ref]),
                    "can_delete_projects": manager.can_delete_projects(
                        database_id, [project_data.project_uid]
                    ),
                }
                self.assertEqual(
                    active_bid_rows,
                    {name: editable and not locked for name in active_bid_rows},
                )
                # Contrast: a Bid-contents feature is blocked by the lock alone.
                self.assertEqual(
                    manager.is_allowed(Feature.EDIT_CONDITION_STRUCTURE),
                    editable and not locked,
                )

    def test_project_tree_structure_permission_ignores_lock_of_other_database(self):
        # The active Bid is locked in test.mdb. Project-tree structure of another
        # database follows only that database's capability (resource kinds pinned).
        project_data = _permissions__ProjectData()
        project_data.locked = True
        checks = []

        class _TargetCapability:
            def is_editable(self, locator, resource=None):
                checks.append((locator, resource))
                return locator == "C:/jobs/target.mdb"

        manager = self._access_manager(project_data, capability=_TargetCapability())
        target = "C:/jobs/target.mdb"
        self.assertTrue(manager.can_edit_project(target, "9"))
        self.assertTrue(manager.can_create_project(target))
        self.assertTrue(manager.can_edit_bid_structure([BidRef(target, "5")]))
        self.assertEqual(
            checks,
            [
                (target, ResourceRef("project", "9", 9)),
                (target, ResourceRef("projects_collection", "database")),
                (target, ResourceRef("bid", "5", 5)),
            ],
        )
        # Negative control: the locked Bid's own database is denied by its capability
        # (editable only for the target), proving the answers above come from the
        # capability and not from the lock.
        self.assertFalse(manager.can_edit_project("C:/jobs/test.mdb", "9"))
        self.assertFalse(manager.can_edit_bid_structure([project_data.bid_ref]))
        project_data.locked = False
        self.assertTrue(manager.can_edit_project(target, "9"))
        self.assertFalse(manager.can_edit_project("C:/jobs/test.mdb", "9"))

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
        self.assertTrue(
            manager.is_allowed_for_active_placement(Feature.PLACE_PLAN_ITEMS)
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
        project_data.locked = False
        self.assertTrue(
            manager.is_allowed_for_active_placement(Feature.PLACE_ANNOTATIONS)
        )
        manager.set_text_annotation_edit_active(True, surface_id="detached-plan")
        self.assertFalse(
            manager.is_allowed_for_active_placement(Feature.PLACE_ANNOTATIONS)
        )
        self.assertFalse(
            manager.is_allowed_for_active_placement(Feature.PLACE_PLAN_ITEMS)
        )

    def test_active_annotation_placement_does_not_bypass_ost_activity(self):
        class _Monitor:
            active = False

            def is_ost_active(self):
                return self.active

        monitor = _Monitor()
        project_data = _permissions__ProjectData()
        manager = UIAccessManager(
            _permissions__EventBus(),
            _permissions__License(),
            monitor,
            project_data,
            _permissions__UiState(project_data.bid_ref),
            _permissions__DatabaseCapability(),
        )
        manager.set_area_placement_active(True, surface_id=MAIN_PLAN_SURFACE_ID)
        self.assertTrue(
            manager.is_allowed_for_active_placement(Feature.PLACE_ANNOTATIONS)
        )
        monitor.active = True
        manager.refresh()
        self.assertFalse(
            manager.is_allowed_for_active_placement(Feature.PLACE_ANNOTATIONS)
        )
        self.assertFalse(
            manager.is_allowed_for_active_placement(Feature.PLACE_PLAN_ITEMS)
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


class ActiveLockedBidTreeActionPermissionTests(unittest.TestCase):
    """Decision Q1: moving, trashing, restoring and cut/paste-moving the status-locked
    ACTIVE Bid, and deleting the project that contains it, are disabled (the services
    refuse them on both backends); every other Bid, project and project-level action
    stays enabled, a locked Bid of another database blocks nothing, and permanent delete
    of a Bid already in 'Deleted Bids' stays allowed (Access delete_bids is unguarded).
    Fake: shared project-data double (active Bid 7 of C:/jobs/test.mdb in project-1),
    capability fake; roles are the editable flag."""

    DATABASE = "C:/jobs/test.mdb"

    def _manager(self, project_data, editable=True):
        return UIAccessManager(
            _permissions__EventBus(),
            _permissions__License(),
            _permissions__TransactionMonitor(),
            project_data,
            _permissions__UiState(project_data.bid_ref),
            _permissions__DatabaseCapability(editable=editable),
        )

    def _locked(self, editable=True):
        project_data = _permissions__ProjectData()
        project_data.locked = True
        return project_data, self._manager(project_data, editable)

    def test_bid_move_and_restore_predicate_blocks_only_the_active_locked_bid(self):
        project_data, manager = self._locked()
        active = BidRef(self.DATABASE, "7")
        other = BidRef(self.DATABASE, "8")
        self.assertFalse(manager.can_edit_bid_structure([active]))
        self.assertFalse(manager.can_edit_bid_structure([other, active]))
        self.assertFalse(manager.can_edit_bid_structure([active, other]))
        self.assertTrue(manager.can_edit_bid_structure([other]))
        # Same Bid uid in another database is a different Bid (Access compares the
        # database too); a differently spelled path of the active database is the same.
        self.assertTrue(
            manager.can_edit_bid_structure([BidRef("C:/jobs/other.mdb", "7")])
        )
        self.assertFalse(
            manager.can_edit_bid_structure([BidRef("C:/jobs/./test.mdb", "7")])
        )
        project_data.locked = False
        self.assertTrue(manager.can_edit_bid_structure([active]))
        self.assertTrue(manager.can_edit_bid_structure([other, active]))

    def test_bid_move_predicate_ignores_a_lock_in_another_database(self):
        project_data = _permissions__ProjectData()
        project_data.locked = True
        project_data.bid_ref = BidRef("C:/jobs/other.mdb", "7")
        manager = self._manager(project_data)
        self.assertTrue(manager.can_edit_bid_structure([BidRef(self.DATABASE, "7")]))
        self.assertTrue(manager.can_delete_bids([BidRef(self.DATABASE, "7")]))
        self.assertTrue(
            manager.can_delete_projects(self.DATABASE, [project_data.project_uid])
        )
        self.assertFalse(manager.can_edit_bid_structure([project_data.bid_ref]))

    def test_trash_and_cut_predicate_blocks_the_active_locked_bid_outside_deleted_bids(
        self,
    ):
        project_data, manager = self._locked()
        active = BidRef(self.DATABASE, "7")
        other = BidRef(self.DATABASE, "8")
        self.assertFalse(manager.can_delete_bids([active]))
        self.assertFalse(manager.can_delete_bids([other, active]))
        self.assertTrue(manager.can_delete_bids([other]))
        # The active Bid already in 'Deleted Bids': its permanent delete is a plain
        # delete_bids on both backends (unguarded), so the command stays enabled.
        project_data.project_uid = "1"
        self.assertTrue(manager.can_delete_bids([active]))
        project_data.project_uid = "project-1"
        project_data.locked = False
        self.assertTrue(manager.can_delete_bids([active]))
        self.assertFalse(manager.can_delete_bids([]))

    def test_cut_paste_move_predicate_blocks_the_active_locked_bid_but_not_copy_paste(
        self,
    ):
        project_data, manager = self._locked()
        active = BidRef(self.DATABASE, "7")
        other = BidRef(self.DATABASE, "8")
        move = Feature.DELETE_BID
        copy = Feature.DUPLICATE_BID
        self.assertFalse(
            manager.is_project_bid_clipboard_allowed(move, self.DATABASE, [active], "3")
        )
        self.assertFalse(
            manager.is_project_bid_clipboard_allowed(
                move, self.DATABASE, [other, active], "3"
            )
        )
        self.assertTrue(
            manager.is_project_bid_clipboard_allowed(move, self.DATABASE, [other], "3")
        )
        # Paste of a copy duplicates the Bid; Access duplicate_bid is not guarded.
        self.assertTrue(
            manager.is_project_bid_clipboard_allowed(copy, self.DATABASE, [active], "3")
        )
        project_data.locked = False
        self.assertTrue(
            manager.is_project_bid_clipboard_allowed(move, self.DATABASE, [active], "3")
        )

    def test_project_delete_predicate_blocks_only_the_project_of_the_active_locked_bid(
        self,
    ):
        project_data, manager = self._locked()
        active_project = project_data.project_uid
        self.assertFalse(manager.can_delete_projects(self.DATABASE, [active_project]))
        self.assertFalse(
            manager.can_delete_projects(self.DATABASE, ["2", active_project])
        )
        self.assertTrue(manager.can_delete_projects(self.DATABASE, ["2"]))
        project_data.locked = False
        self.assertTrue(manager.can_delete_projects(self.DATABASE, [active_project]))

    def test_other_project_level_actions_stay_enabled_on_the_locked_bid(self):
        project_data, manager = self._locked()
        self.assertTrue(manager.can_create_project_tree_items(True))
        self.assertTrue(manager.can_create_bid(self.DATABASE, "project-1"))
        self.assertTrue(manager.can_create_bid(self.DATABASE, None))
        self.assertTrue(manager.can_create_project(self.DATABASE))
        self.assertTrue(manager.can_edit_project(self.DATABASE, "project-1"))
        self.assertTrue(manager.can_maintain_database(self.DATABASE))
        self.assertTrue(manager.can_duplicate_bid(project_data.bid_ref))

    def test_viewer_is_denied_move_trash_and_project_delete_whatever_the_lock(self):
        for locked in (False, True):
            with self.subTest(locked=locked):
                project_data = _permissions__ProjectData()
                project_data.locked = locked
                manager = self._manager(project_data, editable=False)
                other = BidRef(self.DATABASE, "8")
                self.assertFalse(manager.can_edit_bid_structure([other]))
                self.assertFalse(manager.can_delete_bids([other]))
                self.assertFalse(manager.can_delete_projects(self.DATABASE, ["2"]))


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
        self.assertEqual(
            [
                request
                for request in self.capabilities.requests
                if request[1] is not None and request[1].resource_type == "page"
            ],
            [
                ("project.mdb", ResourceRef("page", "page-a", 7)),
                ("project.mdb", ResourceRef("page", "page-b", 7)),
            ],
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
            main,
            PlanSurfaceAccessState(
                can_select_plan_items=True,
                can_place_plan_items=True,
                can_edit_plan_items=True,
                can_place_annotations=True,
                can_continue_annotation_placement=True,
                can_edit_annotations=True,
                can_edit_annotation_text=True,
                can_edit_page_settings=True,
            ),
        )
        self.assertEqual(detached, main)

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
        main = self.manager.get_plan_surface_access(
            self._context("page-a", surface_id=MAIN_PLAN_SURFACE_ID)
        )
        self.assertFalse(main.can_place_annotations)
        self.assertTrue(main.can_continue_annotation_placement)

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

    def test_subscribed_listener_is_deduplicated_and_can_unsubscribe(self):
        calls = []

        def listener():
            calls.append("refresh")

        self.manager.subscribe_access_state_changed(listener)
        self.manager.subscribe_access_state_changed(listener)
        self.manager.refresh()
        self.assertEqual(calls, ["refresh"])
        self.manager.unsubscribe_access_state_changed(listener)
        self.manager.unsubscribe_access_state_changed(listener)
        self.manager.refresh()
        self.assertEqual(calls, ["refresh"])

    def test_clearing_surface_interaction_notifies_only_when_state_existed(self):
        calls = []
        self.manager.subscribe_access_state_changed(lambda: calls.append("refresh"))
        self.manager.clear_plan_surface_interaction("detached-plan")
        self.manager.clear_plan_surface_interaction("")
        self.assertEqual(calls, [])
        self.manager.set_text_annotation_edit_active(True, surface_id="detached-plan")
        self.assertEqual(calls, ["refresh"])
        self.manager.clear_plan_surface_interaction("detached-plan")
        self.assertEqual(calls, ["refresh", "refresh"])
        self.assertEqual(self.manager._surface_interactions, {})
        self.manager.set_area_placement_active(True, surface_id="")
        self.assertEqual(calls, ["refresh", "refresh"])
        self.assertEqual(self.manager._surface_interactions, {})

    def test_ost_activity_forces_placement_exit_when_placement_is_blocked(self):
        exits = []
        self.manager.set_placement_coordinator(
            SimpleNamespace(force_exit=lambda: exits.append(True))
        )
        self.transaction.active = True
        self.events.publish(AppEvents.OST_STATUS_CHANGED, active=True)
        self.assertEqual(exits, [])
        self.ui_state.place_condition_uid = "condition-1"
        self.events.publish(AppEvents.OST_STATUS_CHANGED, active=True)
        self.assertEqual(exits, [True])

    def test_placement_is_kept_when_ost_activity_does_not_block_it(self):
        exits = []
        self.manager.set_placement_coordinator(
            SimpleNamespace(force_exit=lambda: exits.append(True))
        )
        self.ui_state.place_condition_uid = "condition-1"
        self.events.publish(AppEvents.OST_STATUS_CHANGED, active=False)
        self.manager.refresh()
        self.assertEqual(exits, [])

    def test_current_plan_surface_context_reads_main_selection_state(self):
        self.project.annotation_layer_visible = False
        self.assertEqual(
            self.manager.current_plan_surface_context(),
            PlanSurfaceAccessContext(
                surface_id=MAIN_PLAN_SURFACE_ID,
                database_id="project.mdb",
                bid_ref=self.bid_ref,
                page_uid="page-a",
                annotation_layer_visible=False,
            ),
        )
        self.ui_state.bid_ref = None
        self.ui_state.selected_file_path = None
        self.ui_state.active_page_uid = None
        self.assertEqual(
            self.manager.current_plan_surface_context(),
            PlanSurfaceAccessContext(
                surface_id=MAIN_PLAN_SURFACE_ID,
                database_id="",
                bid_ref=None,
                page_uid="",
                annotation_layer_visible=False,
            ),
        )


class ExplicitTargetAccessTests(unittest.TestCase):
    """Per-target checks use the captured database and resource, not Main selection."""

    def setUp(self):
        self.events = _surface_access_support__EventBus()
        self.license = _surface_access_support__License()
        self.capabilities = _surface_access_support__Capabilities()
        self.manager = UIAccessManager(
            self.events,
            self.license,
            _surface_access_support__TransactionMonitor(),
            _surface_access_support__ProjectData(BidRef("project.mdb", "7")),
            _surface_access_support__UiState(None),
            self.capabilities,
        )
        self.addCleanup(self.manager.cleanup)

    def test_bid_job_status_and_structure_use_each_bid_resource(self):
        target = BidRef("other.mdb", "12")
        self.assertTrue(self.manager.can_edit_bid_job_status(target))
        self.assertTrue(self.manager.can_edit_bid_structure([target]))
        self.assertEqual(
            self.capabilities.requests,
            [
                ("other.mdb", ResourceRef("bid", "12", 12)),
                ("other.mdb", ResourceRef("bid", "12", 12)),
            ],
        )
        self.assertFalse(self.manager.can_edit_bid_structure([]))
        self.assertFalse(self.manager.can_delete_bids([]))

    def test_non_numeric_bid_uid_has_no_storage_uid(self):
        self.assertTrue(self.manager.can_edit_bid_job_status(BidRef("a.mdb", "bid-x")))
        self.assertEqual(
            self.capabilities.requests,
            [("a.mdb", ResourceRef("bid", "bid-x", None))],
        )

    def test_read_only_database_denies_each_explicit_target_action(self):
        self.capabilities.database_editable = False
        target = BidRef("project.mdb", "7")
        self.assertFalse(self.manager.can_edit_bid_job_status(target))
        self.assertFalse(self.manager.can_duplicate_bid(target))
        self.assertFalse(self.manager.can_delete_bids([target]))
        self.assertFalse(self.manager.can_edit_bid_structure([target]))
        self.assertFalse(self.manager.can_edit_project("project.mdb", "3"))
        self.assertFalse(self.manager.can_delete_projects("project.mdb", ["3"]))
        self.assertFalse(self.manager.can_create_project("project.mdb"))
        self.assertFalse(self.manager.can_create_bid("project.mdb", "3"))
        self.assertFalse(self.manager.can_import_project_file("project.mdb", "3"))
        self.assertFalse(self.manager.can_maintain_database("project.mdb"))

    def test_delete_bids_requires_every_bid_to_be_editable(self):
        class _OneReadOnlyBid:
            def is_editable(self, _locator, resource=None):
                return resource is None or resource.resource_id != "2"

        self.manager._database_capability_service = _OneReadOnlyBid()
        first = BidRef("project.mdb", "1")
        second = BidRef("project.mdb", "2")
        self.assertTrue(self.manager.can_delete_bids([first]))
        self.assertFalse(self.manager.can_delete_bids([first, second]))
        self.assertFalse(self.manager.can_delete_bids([second, first]))

    def test_project_creation_checks_project_and_collection_resources(self):
        self.assertFalse(self.manager.can_create_project(""))
        self.assertFalse(self.manager.can_create_bid("", "3"))
        self.assertFalse(self.manager.can_import_project_file("", "3"))
        self.assertEqual(self.capabilities.requests, [])
        self.assertTrue(self.manager.can_create_project("project.mdb"))
        self.assertTrue(self.manager.can_create_bid("project.mdb", "3"))
        self.assertTrue(self.manager.can_create_bid("project.mdb", None))
        self.assertEqual(
            self.capabilities.requests,
            [
                ("project.mdb", ResourceRef("projects_collection", "database")),
                ("project.mdb", ResourceRef("project", "3")),
                ("project.mdb", ResourceRef("project_bids", "3")),
                ("project.mdb", ResourceRef("project_bids", "orphan")),
            ],
        )

    def test_project_bid_clipboard_requires_same_database_and_editable_targets(self):
        target = BidRef("C:/Jobs/Project.mdb", "5")
        self.assertTrue(
            self.manager.is_project_bid_clipboard_allowed(
                Feature.DUPLICATE_BID, "c:\\jobs\\project.mdb", [target], "3"
            )
        )
        self.assertFalse(
            self.manager.is_project_bid_clipboard_allowed(
                Feature.DUPLICATE_BID, "other.mdb", [target], "3"
            )
        )
        self.assertFalse(
            self.manager.is_project_bid_clipboard_allowed(
                Feature.DUPLICATE_BID, "C:/Jobs/Project.mdb", [], "3"
            )
        )
        self.assertFalse(
            self.manager.is_project_bid_clipboard_allowed(
                Feature.EDIT_PLAN_ITEMS, "C:/Jobs/Project.mdb", [target], "3"
            )
        )
        self.capabilities.database_editable = False
        self.assertFalse(
            self.manager.is_project_bid_clipboard_allowed(
                Feature.DUPLICATE_BID, "C:/Jobs/Project.mdb", [target], "3"
            )
        )

    def test_close_database_needs_a_database_id_but_no_license(self):
        self.assertTrue(self.manager.can_close_database("project.mdb"))
        self.assertFalse(self.manager.can_close_database(""))
        self.license.valid = False
        self.assertTrue(self.manager.can_close_database("project.mdb"))
        self.assertFalse(self.manager.can_edit_project("project.mdb", "3"))


class PlanSurfaceContextPathIdentityTests(unittest.TestCase):
    """Decision S2: a plan surface context is consistent when its database path and its
    Bid's path name the same database (normalize_path, like the manager's other path
    comparisons); a context for another database still fails closed."""

    DISPLAYED = "C:\\Jobs\\Bid.mdb"
    ALIASES = (
        ("lower case with slashes", "c:/jobs/bid.mdb"),
        ("upper case", "C:\\JOBS\\BID.MDB"),
        ("doubled separator", "C:\\Jobs\\\\Bid.mdb"),
        ("current-directory segment", "C:\\Jobs\\.\\Bid.mdb"),
        ("parent-directory segment", "C:\\Jobs\\Sub\\..\\Bid.mdb"),
        ("trailing separator", "C:\\Jobs\\Bid.mdb\\"),
    )
    OTHERS = (
        ("other file name", "C:\\Jobs\\Other.mdb"),
        ("other folder", "C:\\Jobs2\\Bid.mdb"),
        ("longer file name", "C:\\Jobs\\Bid.mdb.bak"),
        ("other drive", "D:\\Jobs\\Bid.mdb"),
    )

    def _manager(self, bid_ref):
        self.capabilities = _surface_access_support__Capabilities()
        manager = UIAccessManager(
            _surface_access_support__EventBus(),
            _surface_access_support__License(),
            _surface_access_support__TransactionMonitor(),
            _surface_access_support__ProjectData(bid_ref),
            _surface_access_support__UiState(bid_ref),
            self.capabilities,
        )
        self.addCleanup(manager.cleanup)
        return manager

    @staticmethod
    def _context(bid_ref, database_id):
        return PlanSurfaceAccessContext(
            surface_id="detached-plan",
            database_id=database_id,
            bid_ref=bid_ref,
            page_uid="page-a",
            annotation_layer_visible=True,
        )

    def test_a_context_whose_database_path_is_another_spelling_of_the_bids_is_valid(
        self,
    ):
        for label, alias in self.ALIASES:
            for side, bid_path, database_id in (
                ("context path", self.DISPLAYED, alias),
                ("bid path", alias, self.DISPLAYED),
            ):
                with self.subTest(label, side=side):
                    bid_ref = BidRef(bid_path, "7")
                    manager = self._manager(bid_ref)
                    state = manager.get_plan_surface_access(
                        self._context(bid_ref, database_id)
                    )
                    self.assertTrue(state.can_edit_page_settings)
                    self.assertTrue(state.can_place_annotations)
                    self.assertEqual(
                        [
                            request
                            for request in self.capabilities.requests
                            if request[1] is not None
                            and request[1].resource_type == "page"
                        ],
                        [(database_id, ResourceRef("page", "page-a", 7))],
                    )

    def test_a_context_for_another_database_still_fails_closed(self):
        bid_ref = BidRef(self.DISPLAYED, "7")
        for label, other in self.OTHERS + (("empty path", ""),):
            with self.subTest(label):
                manager = self._manager(bid_ref)
                self.assertEqual(
                    manager.get_plan_surface_access(self._context(bid_ref, other)),
                    PlanSurfaceAccessState(),
                )
                self.assertEqual(self.capabilities.requests, [])

    def test_an_aliased_database_path_still_needs_the_current_bid(self):
        bid_ref = BidRef(self.DISPLAYED, "7")
        manager = self._manager(BidRef(self.DISPLAYED, "8"))
        self.assertEqual(
            manager.get_plan_surface_access(self._context(bid_ref, "c:/jobs/bid.mdb")),
            PlanSurfaceAccessState(),
        )
        self.assertEqual(self.capabilities.requests, [])
