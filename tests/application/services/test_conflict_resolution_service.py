import unittest
from ost_visualizer.application.dtos.collaboration_dtos import ResourceRef
from ost_visualizer.application.dtos.conflict_resolution_dtos import (
    ConflictResolutionAction,
    ConflictResolutionPlan,
)
from ost_visualizer.application.dtos.local_draft_dtos import LocalDraftConflict
from ost_visualizer.application.services.conflict_resolution_service import (
    ConflictResolutionService,
)


class ConflictResolutionServiceCollaborationTests(unittest.TestCase):
    def test_first_release_conflict_plan_never_auto_merges_geometry(self):
        service = ConflictResolutionService()
        for draft_id in ("first-draft", "second-draft"):
            with self.subTest(draft_id=draft_id):
                conflict = LocalDraftConflict(
                    draft_id=draft_id,
                    changed_resource=ResourceRef("takeoff", "42", 8),
                    draft_type="vertex_drag",
                    owning_surface="plan",
                )
                plan = service.plan(conflict)
                self.assertEqual(
                    plan,
                    ConflictResolutionPlan(
                        draft_id,
                        (
                            ConflictResolutionAction.RELOAD,
                            ConflictResolutionAction.DISCARD_DRAFT,
                            ConflictResolutionAction.CANCEL_READ_ONLY,
                        ),
                    ),
                )

    def test_plan_is_independent_of_the_conflicted_resource_and_surface(self):
        service = ConflictResolutionService()
        expected_actions = (
            ConflictResolutionAction.RELOAD,
            ConflictResolutionAction.DISCARD_DRAFT,
            ConflictResolutionAction.CANCEL_READ_ONLY,
        )
        for resource, draft_type, surface in (
            (
                ResourceRef("condition", "9", 3),
                "conditions_editor",
                "condition-sidebar",
            ),
            (ResourceRef("annotation", "rect/4", 3), "annotation_text", "detached-2d"),
            (ResourceRef("cover_sheet", "3", 3), "cover_sheet_editor", "dialog"),
            (ResourceRef("database", "database"), "project_write", "tree"),
        ):
            with self.subTest(resource=resource.resource_type):
                plan = service.plan(
                    LocalDraftConflict("draft-x", resource, draft_type, surface)
                )
                self.assertEqual(plan.draft_id, "draft-x")
                self.assertEqual(plan.actions, expected_actions)
                self.assertEqual(
                    [action.value for action in plan.actions],
                    ["reload", "discard_draft", "cancel_read_only"],
                )
