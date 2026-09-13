import unittest

from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    ResourceRef,
)
from ost_visualizer.application.dtos.local_draft_dtos import LocalDraftState
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.local_draft_registry import LocalDraftRegistry
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter, _RecordedMutation
from tests import test_sql_global_condition_scope
from tests.test_sql_collaboration_phase4 import _change


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

    def test_coalesced_conditions_notify_before_replacing_editor_objects(self):
        fixture = test_sql_global_condition_scope.GlobalConditionScopeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        context = fixture.context
        old = Condition("42", name="Editor baseline")
        context.data.replace_condition_family(context.fixture.bid_ref, {"42": old}, {})
        drafts = context.coordinator._local_drafts
        draft = self.begin(drafts, ResourceRef("condition", "42", 8))
        notifications = []

        def notified(**payload):
            self.assertIs(context.data.get_bid_conditions()["42"], old)
            self.assertEqual(context.runtime.acknowledged_version, 0)
            notifications.append(payload)

        context.events.subscribe(AppEvents.SYNCHRONIZATION_CONFLICT, notified)
        records = [
            _RecordedMutation(
                ResourceRef("condition", str(uid), 8), ChangeOperation.UPDATE
            )
            for uid in range(42, 493)
        ]
        coalesced, hydrated = fixture.deliver(records)
        self.assertEqual(
            [r.resource for r in coalesced],
            [ResourceRef("conditions_collection", "8", 8)],
        )
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["draft_id"], draft.draft_id)
        self.assertEqual(drafts.get(draft.draft_id).state, LocalDraftState.CONFLICTED)
        self.assertIs(context.data.get_bid_conditions()["42"], old)
        self.assertEqual(context.runtime.acknowledged_version, 0)
        self.assertTrue(context.runtime.pending_delivery)
        drafts.finish(draft.draft_id)
        self.assertTrue(context.coordinator._reconciliation.apply(hydrated).applied)
        self.assertIs(context.data.get_bid_conditions()["42"], fixture.rows[8]["42"])

    def test_same_bid_collection_overlaps_entities_and_dependencies(self):
        for kind in ("condition", "page", "area", "annotation", "layer", "takeoff"):
            for dependency in (False, True):
                with self.subTest(kind=kind, dependency=dependency):
                    records = [
                        _RecordedMutation(
                            ResourceRef(
                                kind,
                                f"text/{uid}" if kind == "annotation" else str(uid),
                                8,
                            ),
                            ChangeOperation.UPDATE,
                        )
                        for uid in range(1, 452)
                    ]
                    (collection,) = SqlProjectWriter._coalesce_records(records)
                    drafts = LocalDraftRegistry()
                    draft = self.begin(
                        drafts, records[0].resource, dependency=dependency
                    )
                    conflicts = drafts.conflicts_for_changes(
                        "database", (_change("database", collection.resource),)
                    )
                    self.assertEqual([c.draft_id for c in conflicts], [draft.draft_id])

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


if __name__ == "__main__":
    unittest.main()
