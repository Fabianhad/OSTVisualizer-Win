from ..dtos.conflict_resolution_dtos import (
    ConflictResolutionAction,
    ConflictResolutionPlan,
)
from ..dtos.local_draft_dtos import LocalDraftConflict


class ConflictResolutionService:
    def plan(self, conflict: LocalDraftConflict) -> ConflictResolutionPlan:
        return ConflictResolutionPlan(
            conflict.draft_id,
            (
                ConflictResolutionAction.RELOAD,
                ConflictResolutionAction.DISCARD_DRAFT,
                ConflictResolutionAction.CANCEL_READ_ONLY,
            ),
        )
