from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from .collaboration_dtos import ConcurrencyToken, ResourceLock, ResourceRef


class LocalDraftState(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    CONFLICTED = "conflicted"


@dataclass(frozen=True)
class LocalDraft:
    draft_id: str
    draft_type: str
    database_id: str
    bid_uid: Optional[int]
    page_uid: Optional[int]
    owning_surface: str
    affected_resources: tuple[ResourceRef, ...]
    dependency_resources: tuple[ResourceRef, ...]
    base_tokens: tuple[tuple[ResourceRef, ConcurrencyToken], ...]
    state: LocalDraftState
    lease: Optional[ResourceLock] = None


@dataclass(frozen=True)
class LocalDraftConflict:
    draft_id: str
    changed_resource: ResourceRef
    draft_type: str
    owning_surface: str
