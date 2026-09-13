import unittest

from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    ResourceRef,
)
from ost_visualizer.application.services.local_draft_registry import LocalDraftRegistry
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter, _RecordedMutation
from tests import test_sql_global_condition_scope
from tests.test_sql_collaboration_phase4 import _change


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

    def test_individual_condition_notifies_cover_sheet_collection_dependency(self):
        fixture = test_sql_global_condition_scope.GlobalConditionScopeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        context = fixture.context
        old = Condition("42", name="Opening snapshot")
        context.data.replace_condition_family(context.fixture.bid_ref, {"42": old}, {})
        registry = context.coordinator._local_drafts
        draft = self.begin(registry, ResourceRef("conditions_collection", "8", 8))
        notices = []

        def notified(**payload):
            self.assertIs(context.data.get_bid_conditions()["42"], old)
            self.assertEqual(context.runtime.acknowledged_version, 0)
            notices.append(payload)

        context.events.subscribe(AppEvents.SYNCHRONIZATION_CONFLICT, notified)
        record = _RecordedMutation(
            ResourceRef("condition", "42", 8), ChangeOperation.UPDATE
        )
        records, hydrated = fixture.deliver([record])
        self.assertEqual(records, (record,))
        self.assertEqual([n["draft_id"] for n in notices], [draft.draft_id])
        self.assertIs(context.data.get_bid_conditions()["42"], old)
        self.assertEqual(context.runtime.acknowledged_version, 0)
        self.assertTrue(context.runtime.pending_delivery)
        registry.finish(draft.draft_id)
        self.assertTrue(context.coordinator._reconciliation.apply(hydrated).applied)
        self.assertIs(context.data.get_bid_conditions()["42"], fixture.rows[8]["42"])

    def test_entity_records_overlap_typed_collection_drafts(self):
        for entity, collection in (
            ("condition", "conditions_collection"),
            ("page", "pages_collection"),
            ("area", "areas_collection"),
            ("annotation", "annotations_collection"),
            ("takeoff", "takeoffs_collection"),
            ("layer", "layers_collection"),
        ):
            for dependency in (False, True):
                with self.subTest(entity=entity, dependency=dependency):
                    registry = LocalDraftRegistry()
                    scope = ResourceRef(collection, "8", 8)
                    if dependency:
                        draft = self.begin(registry, scope)
                    else:
                        draft = registry.begin(
                            draft_type="collection_editor",
                            database_id="database",
                            bid_uid=8,
                            page_uid=None,
                            owning_surface="dialog",
                            affected_resources=(scope,),
                        )
                    resource = ResourceRef(
                        entity, "text/42" if entity == "annotation" else "42", 8
                    )
                    records = SqlProjectWriter._coalesce_records(
                        [_RecordedMutation(resource, ChangeOperation.UPDATE)]
                    )
                    self.assertEqual([r.resource for r in records], [resource])
                    self.assertEqual(
                        [
                            c.draft_id
                            for c in registry.conflicts_for_changes(
                                "database", (_change("database", resource),)
                            )
                        ],
                        [draft.draft_id],
                    )

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


if __name__ == "__main__":
    unittest.main()
