import unittest

from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    ResourceRef,
)
from ost_visualizer.application.services.local_draft_registry import LocalDraftRegistry
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter, _RecordedMutation
from tests.test_sql_collaboration_phase4 import _change
from ost_visualizer.application.dtos.local_draft_dtos import LocalDraftState
from ost_visualizer.application.events.app_events import AppEvents
from tests import test_sql_global_bid_family_scope


class GlobalCoverSheetConflictTests(unittest.TestCase):
    def test_global_family_changes_match_entity_and_dependency_drafts(self):
        for entity_type in (
            "condition",
            "page",
            "area",
            "takeoff",
            "annotation",
            "layer",
            "cover_sheet",
        ):
            with self.subTest(entity_type=entity_type):
                records = [
                    _RecordedMutation(
                        ResourceRef(
                            entity_type,
                            f"text/{bid}" if entity_type == "annotation" else str(bid),
                            bid,
                        ),
                        ChangeOperation.UPDATE,
                    )
                    for bid in range(8, 459)
                ]
                (global_record,) = SqlProjectWriter._coalesce_records(records)
                drafts = LocalDraftRegistry()
                draft = drafts.begin(
                    draft_type="editor",
                    database_id="database",
                    bid_uid=8,
                    page_uid=None,
                    owning_surface="dialog",
                    affected_resources=(ResourceRef("bid", "8", 8),),
                    dependency_resources=(records[0].resource,),
                )
                conflicts = drafts.conflicts_for_changes(
                    "database",
                    (
                        _change(
                            "database",
                            global_record.resource,
                            4,
                            operation=global_record.operation,
                        ),
                    ),
                )
                self.assertEqual([c.draft_id for c in conflicts], [draft.draft_id])

    def test_global_cover_sheet_notifies_open_editor_before_acknowledgement(self):
        fixture = test_sql_global_bid_family_scope.GlobalBidFamilyScopeTests()
        context, _reader, _connection, hydrated = fixture.make_fixture(
            "cover_sheet", True
        )
        self.addCleanup(fixture.doCleanups)
        context.data.replace_cover_sheet_data(
            "database", "8", {"name": "Opening draft"}
        )
        drafts = context.coordinator._local_drafts
        draft = drafts.begin(
            draft_type="cover_sheet",
            database_id="database",
            bid_uid=8,
            page_uid=None,
            owning_surface="cover-sheet-dialog",
            affected_resources=(ResourceRef("cover_sheet", "8", 8),),
        )
        runtime = context.runtime
        drafts.activate(draft.draft_id, (), runtime_generation=runtime.generation)
        context.coordinator._on_remote_batch(
            (
                "database",
                runtime.generation,
                runtime.session_generation,
                hydrated,
                context.fixture.model.current_bid,
            )
        )
        notifications = [
            payload
            for event, payload in context.events.published
            if event == AppEvents.SYNCHRONIZATION_CONFLICT
        ]
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["draft_id"], draft.draft_id)
        self.assertIn("reload", notifications[0]["allowed_actions"])
        self.assertEqual(drafts.get(draft.draft_id).state, LocalDraftState.CONFLICTED)
        self.assertEqual(runtime.acknowledged_version, 0)
        self.assertTrue(runtime.pending_delivery)
        self.assertEqual(
            context.data.get_cover_sheet_snapshot("database", "8"),
            {"name": "Opening draft"},
        )

    def test_global_cover_sheet_does_not_conflict_with_other_database_or_family(self):
        fixture = test_sql_global_bid_family_scope.GlobalBidFamilyScopeTests()
        context, _reader, _connection, hydrated = fixture.make_fixture(
            "cover_sheet", True
        )
        self.addCleanup(fixture.doCleanups)
        drafts = context.coordinator._local_drafts
        for database, resource in (
            ("other-database", ResourceRef("cover_sheet", "8", 8)),
            ("database", ResourceRef("page", "1", 8)),
        ):
            drafts.begin(
                draft_type="editor",
                database_id=database,
                bid_uid=8,
                page_uid=None,
                owning_surface="dialog",
                affected_resources=(resource,),
            )
        fixture.check_projection(context, hydrated)
        self.assertFalse(
            any(
                event == AppEvents.SYNCHRONIZATION_CONFLICT
                for event, _ in context.events.published
            )
        )
        self.assertEqual(
            context.data.get_cover_sheet_snapshot("database", "8")["name"], "New"
        )


if __name__ == "__main__":
    unittest.main()
