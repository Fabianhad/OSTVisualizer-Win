from dataclasses import dataclass
from enum import Enum


class ConflictResolutionAction(str, Enum):
    RELOAD = "reload"
    DISCARD_DRAFT = "discard_draft"
    CANCEL_READ_ONLY = "cancel_read_only"


@dataclass(frozen=True)
class ConflictResolutionPlan:
    draft_id: str
    actions: tuple[ConflictResolutionAction, ...]
