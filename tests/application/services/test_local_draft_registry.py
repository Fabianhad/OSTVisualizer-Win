import unittest
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    ChangeOperation,
    CollaborationMutationType,
    CollaborationPollingPolicy,
    CollaborationShutdownState,
    CollaborationStatus,
    ConcurrencyToken,
    DatabaseChange,
    DatabaseChangeBatch,
    DatabaseChangePollResult,
    DatabaseMutationRequest,
    DatabaseMutationResult,
    DatabaseSession,
    DurableOperationResult,
    EditLeaseHandle,
    EditLeaseLoss,
    EditLeaseResult,
    HydratedDatabaseChangeBatch,
    MutationExecutionResult,
    MutationOutcomeStatus,
    PendingMutationState,
    PendingSqlOperationRecord,
    PresenceMode,
    QueuedMutationRequest,
    QueuedMutationResult,
    ReconciliationFailureKind,
    ReconciliationResult,
    ResourceLock,
    ResourceRef,
    SynchronizationConflict,
    SynchronizationConflictKind,
    SynchronizationState,
    queued_takeoff_preview_uid,
    session_identities_equal,
)
from ost_visualizer.application.dtos.local_draft_dtos import (
    LocalDraftConflict,
    LocalDraftState,
)
from ost_visualizer.application.services.local_draft_registry import LocalDraftRegistry
from tests.helpers.sql.collaboration import (
    _change,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    ResourceRef,
)
from ost_visualizer.application.dtos.local_draft_dtos import LocalDraftState
from tests.helpers.sql.collaboration import _change


class LocalDraftRegistryCollaborationTests(unittest.TestCase):
    def test_local_drafts_cannot_overlap_an_existing_dependency(self):
        condition = ResourceRef("condition", "42", 8)
        takeoff = ResourceRef("takeoff", "395", 8)
        drafts = LocalDraftRegistry()
        draft = drafts.begin(
            draft_type="takeoff-geometry",
            database_id="database",
            bid_uid=8,
            page_uid=3,
            owning_surface="plan-view",
            affected_resources=(takeoff,),
            dependency_resources=(condition,),
        )
        with self.assertRaisesRegex(ValueError, "already owns"):
            drafts.begin(
                draft_type="condition-properties",
                database_id="database",
                bid_uid=8,
                page_uid=None,
                owning_surface="condition-dialog",
                affected_resources=(condition,),
            )

    def test_local_draft_overlap_ignores_optional_bid_context(self):
        drafts = LocalDraftRegistry()
        stored = ResourceRef("takeoff", "41")
        requested = ResourceRef("takeoff", "41", 7)
        drafts.begin(
            draft_type="takeoff-mutation",
            database_id="database",
            bid_uid=None,
            page_uid=None,
            owning_surface="plan-view",
            affected_resources=(stored,),
        )
        with self.assertRaisesRegex(ValueError, "already owns"):
            drafts.begin(
                draft_type="takeoff-mutation",
                database_id="database",
                bid_uid=7,
                page_uid=None,
                owning_surface="detached-plan",
                affected_resources=(requested,),
            )

    def test_local_draft_remote_conflict_ignores_optional_bid_context(self):
        drafts = LocalDraftRegistry()
        stored = ResourceRef("takeoff", "41")
        changed = ResourceRef("takeoff", "41", 7)
        draft = drafts.begin(
            draft_type="takeoff-mutation",
            database_id="database",
            bid_uid=None,
            page_uid=None,
            owning_surface="plan-view",
            affected_resources=(stored,),
        )
        conflicts = drafts.conflicts_for_changes(
            "database", (_change("database", changed, 2),)
        )
        self.assertEqual(
            tuple(conflict.draft_id for conflict in conflicts), (draft.draft_id,)
        )

    def test_local_draft_version_state_ignores_optional_bid_context(self):
        drafts = LocalDraftRegistry()
        stored = ResourceRef("takeoff", "41")
        contextual = ResourceRef("takeoff", "41", 7)
        original = ConcurrencyToken(b"\x00" * 7 + b"\x01")
        updated = ConcurrencyToken(b"\x00" * 7 + b"\x02")
        draft = drafts.begin(
            draft_type="takeoff-mutation",
            database_id="database",
            bid_uid=None,
            page_uid=None,
            owning_surface="plan-view",
            affected_resources=(stored,),
            base_tokens=((stored, original),),
        )
        self.assertEqual(drafts.base_token("database", contextual), original)
        drafts.apply_local_versions("database", {contextual: updated})
        self.assertEqual(drafts.base_token("database", contextual), updated)
        self.assertEqual(drafts.get(draft.draft_id).base_tokens, ((stored, updated),))

    def test_local_draft_tracks_active_editor_and_all_leases(self):
        first = ResourceRef("takeoff", "1", 8)
        second = ResourceRef("takeoff", "2", 8)
        drafts = LocalDraftRegistry()
        draft = drafts.begin(
            draft_type="takeoff-geometry",
            database_id="database",
            bid_uid=8,
            page_uid=3,
            owning_surface="detached-2d",
            affected_resources=(first, second),
            operation_id="move-takeoffs",
        )
        locks = (
            ResourceLock("database", first, "first-token"),
            ResourceLock("database", second, "second-token"),
        )
        drafts.activate(draft.draft_id, locks, runtime_generation=7)
        active = drafts.get(draft.draft_id)
        self.assertEqual(active.state, LocalDraftState.ACTIVE)
        self.assertEqual(active.leases, locks)
        self.assertEqual(active.runtime_generation, 7)
        drafts.finish(draft.draft_id)
        self.assertIsNone(drafts.get(draft.draft_id))


class BidCollectionDraftConflictTests(unittest.TestCase):
    def begin(self, drafts, resource, database="database", dependency=False):
        draft = drafts.begin(
            draft_type="conditions_editor",
            database_id=database,
            bid_uid=resource.bid_uid,
            page_uid=None,
            owning_surface="condition-sidebar",
            affected_resources=(
                (ResourceRef("bid", str(resource.bid_uid), resource.bid_uid),)
                if dependency
                else (resource,)
            ),
            dependency_resources=(resource,) if dependency else (),
        )
        drafts.activate(draft.draft_id, (), runtime_generation=1)
        return draft

    def test_collection_isolation_and_exact_match_controls(self):
        resource = ResourceRef("condition", "42", 8)
        for database, incoming in (
            ("database", ResourceRef("conditions_collection", "9", 9)),
            ("other", ResourceRef("conditions_collection", "8", 8)),
            ("database", ResourceRef("pages_collection", "8", 8)),
            ("database", ResourceRef("condition", "43", 8)),
        ):
            with self.subTest(database=database, incoming=incoming):
                drafts = LocalDraftRegistry()
                draft = self.begin(drafts, resource)
                self.assertEqual(
                    drafts.conflicts_for_changes(
                        database, (_change(database, incoming),)
                    ),
                    (),
                )
                self.assertEqual(
                    drafts.get(draft.draft_id).state, LocalDraftState.ACTIVE
                )
        for exact in (resource, ResourceRef("cover_sheet", "8", 8)):
            drafts = LocalDraftRegistry()
            draft = self.begin(drafts, exact)
            self.assertEqual(
                [
                    c.draft_id
                    for c in drafts.conflicts_for_changes(
                        "database", (_change("database", exact),)
                    )
                ],
                [draft.draft_id],
            )


class EntityCollectionDraftConflictTests(unittest.TestCase):
    def begin(self, registry, collection):
        draft = registry.begin(
            draft_type="cover_sheet_editor",
            database_id="database",
            bid_uid=8,
            page_uid=None,
            owning_surface="cover-sheet-dialog",
            affected_resources=(ResourceRef("cover_sheet", "8", 8),),
            dependency_resources=(collection,),
        )
        registry.activate(draft.draft_id, (), runtime_generation=1)
        return draft

    def test_isolation_and_exact_collection_control(self):
        scope = ResourceRef("areas_collection", "8", 8)
        for database, resource in (
            ("database", ResourceRef("area", "42", 9)),
            ("other", ResourceRef("area", "42", 8)),
            ("database", ResourceRef("condition", "42", 8)),
        ):
            with self.subTest(database=database, resource=resource):
                registry = LocalDraftRegistry()
                self.begin(registry, scope)
                self.assertEqual(
                    registry.conflicts_for_changes(
                        database, (_change(database, resource),)
                    ),
                    (),
                )
        registry = LocalDraftRegistry()
        draft = self.begin(registry, scope)
        self.assertEqual(
            [
                c.draft_id
                for c in registry.conflicts_for_changes(
                    "database", (_change("database", scope),)
                )
            ],
            [draft.draft_id],
        )
