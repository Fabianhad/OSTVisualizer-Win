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
