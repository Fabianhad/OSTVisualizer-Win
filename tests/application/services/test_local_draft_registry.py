import unittest
from dataclasses import replace
from ost_visualizer.application.dtos.collaboration_dtos import (
    ConcurrencyToken,
    ResourceLock,
    ResourceRef,
)
from ost_visualizer.application.dtos.local_draft_dtos import (
    LocalDraftConflict,
    LocalDraftState,
)
from ost_visualizer.application.services.local_draft_registry import LocalDraftRegistry
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
        self.assertIs(drafts.get(draft.draft_id), draft)
        drafts.finish(draft.draft_id)
        replacement = drafts.begin(
            draft_type="condition-properties",
            database_id="database",
            bid_uid=8,
            page_uid=None,
            owning_surface="condition-dialog",
            affected_resources=(condition,),
        )
        self.assertIs(drafts.get(replacement.draft_id), replacement)

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
            conflicts,
            (
                LocalDraftConflict(
                    draft.draft_id, changed, "takeoff-mutation", "plan-view"
                ),
            ),
        )
        self.assertEqual(drafts.get(draft.draft_id).state, LocalDraftState.CONFLICTED)

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
        self.assertEqual(
            active,
            replace(
                draft, state=LocalDraftState.ACTIVE, leases=locks, runtime_generation=7
            ),
        )
        self.assertEqual(draft.state, LocalDraftState.PENDING)
        self.assertEqual(draft.leases, ())
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
        return drafts.get(draft.draft_id)

    def test_collection_changes_conflict_with_entities_and_dependencies(self):
        for family, entity in (
            ("conditions_collection", "condition"),
            ("conditions_collection", "condition_folder"),
            ("areas_collection", "area"),
            ("pages_collection", "page"),
            ("layers_collection", "layer"),
            ("takeoffs_collection", "takeoff"),
        ):
            for dependency in (False, True):
                with self.subTest(family=family, entity=entity, dependency=dependency):
                    registry = LocalDraftRegistry()
                    draft = self.begin(
                        registry, ResourceRef(entity, "42", 8), dependency=dependency
                    )
                    incoming = ResourceRef(family, "8", 8)
                    conflicts = registry.conflicts_for_changes(
                        "database",
                        (
                            _change("database", incoming),
                            _change("database", incoming, 2),
                        ),
                    )
                    self.assertEqual(
                        conflicts,
                        (
                            LocalDraftConflict(
                                draft.draft_id,
                                incoming,
                                "conditions_editor",
                                "condition-sidebar",
                            ),
                        ),
                    )
                    self.assertEqual(
                        registry.get(draft.draft_id),
                        replace(draft, state=LocalDraftState.CONFLICTED),
                    )

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
        return registry.get(draft.draft_id)

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

    def test_member_changes_conflict_once_with_collection_dependency(self):
        for family, entity in (
            ("areas_collection", "area"),
            ("conditions_collection", "condition"),
            ("conditions_collection", "condition_folder"),
            ("pages_collection", "page"),
            ("layers_collection", "layer"),
            ("takeoffs_collection", "takeoff"),
        ):
            with self.subTest(family=family, entity=entity):
                registry = LocalDraftRegistry()
                draft = self.begin(registry, ResourceRef(family, "8", 8))
                first = ResourceRef(entity, "42", 8)
                changes = (
                    _change("database", first),
                    _change("database", ResourceRef(entity, "43", 8), 2),
                )
                conflicts = registry.conflicts_for_changes("database", changes)
                self.assertEqual(
                    conflicts,
                    (
                        LocalDraftConflict(
                            draft.draft_id,
                            first,
                            "cover_sheet_editor",
                            "cover-sheet-dialog",
                        ),
                    ),
                )
                self.assertEqual(
                    registry.get(draft.draft_id),
                    replace(draft, state=LocalDraftState.CONFLICTED),
                )


class LocalDraftLifecycleTests(unittest.TestCase):
    def test_begin_snapshots_inputs_and_finish_releases_only_its_database_owner(self):
        registry = LocalDraftRegistry()
        first = ResourceRef("condition", "41", 8)
        second = ResourceRef("condition", "42", 8)
        token = ConcurrencyToken(b"\x01" * 8)
        resources = [second, first, first]
        versions = [(first, token)]
        options = dict(
            draft_type="editor",
            database_id="database",
            bid_uid=8,
            page_uid=None,
            owning_surface="sidebar",
            affected_resources=resources,
            base_tokens=versions,
        )
        with self.assertRaisesRegex(ValueError, "at least one resource"):
            registry.begin(**dict(options, affected_resources=()))
        draft = registry.begin(**options)
        other = registry.begin(**dict(options, database_id="other"))
        resources.clear()
        versions.clear()
        self.assertEqual(draft.affected_resources, (first, second))
        self.assertEqual(draft.base_tokens, ((first, token),))
        self.assertEqual(draft.operation_id, "editor")
        registry.finish(draft.draft_id)
        registry.finish(draft.draft_id)
        self.assertIsNone(registry.get(draft.draft_id))
        self.assertIs(registry.get(other.draft_id), other)
        self.assertIsNone(registry.base_token("database", first))
        self.assertEqual(registry.base_token("other", first), token)
        for action in (
            lambda: registry.activate(draft.draft_id, (), runtime_generation=1),
            lambda: registry.set_base_tokens(draft.draft_id, ()),
        ):
            with self.assertRaisesRegex(ValueError, "no longer active"):
                action()
        self.assertIs(registry.get(other.draft_id), other)

    def test_base_token_replacement_is_detached_and_local_save_does_not_advance_dependencies(
        self,
    ):
        registry = LocalDraftRegistry()
        condition = ResourceRef("condition", "42", 8)
        takeoff = ResourceRef("takeoff", "1", 8)
        initial = ConcurrencyToken(b"\x01" * 8)
        current = ConcurrencyToken(b"\x02" * 8)
        draft = registry.begin(
            draft_type="geometry",
            database_id="database",
            bid_uid=8,
            page_uid=3,
            owning_surface="plan",
            affected_resources=(takeoff,),
            dependency_resources=(condition,),
        )
        versions = [(takeoff, initial), (condition, initial)]
        registry.set_base_tokens(draft.draft_id, versions)
        versions.clear()
        self.assertEqual(
            registry.get(draft.draft_id).base_tokens,
            ((condition, initial), (takeoff, initial)),
        )
        registry.apply_local_versions(
            "database", {condition: current, takeoff: current}
        )
        self.assertEqual(registry.base_token("database", condition), initial)
        self.assertEqual(registry.base_token("database", takeoff), current)
        self.assertEqual(
            registry.get(draft.draft_id).base_tokens,
            ((condition, initial), (takeoff, current)),
        )
