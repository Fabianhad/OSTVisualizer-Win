from __future__ import annotations
import threading
import uuid
from dataclasses import replace
from typing import Optional
from ..dtos.collaboration_dtos import (
    ConcurrencyToken,
    DatabaseChange,
    ResourceLock,
    ResourceRef,
)
from ..dtos.local_draft_dtos import LocalDraft, LocalDraftConflict, LocalDraftState


class LocalDraftRegistry:
    def __init__(self) -> None:
        self._drafts: dict[str, LocalDraft] = {}
        self._lock = threading.Lock()

    def begin(
        self,
        *,
        draft_type: str,
        database_id: str,
        bid_uid: Optional[int],
        page_uid: Optional[int],
        owning_surface: str,
        affected_resources: tuple[ResourceRef, ...],
        dependency_resources: tuple[ResourceRef, ...] = (),
        base_tokens: tuple[tuple[ResourceRef, ConcurrencyToken], ...] = (),
        operation_id: str = "",
    ) -> LocalDraft:
        if not affected_resources:
            raise ValueError("A local draft must affect at least one resource")
        draft = LocalDraft(
            draft_id=str(uuid.uuid4()),
            draft_type=draft_type,
            database_id=database_id,
            bid_uid=bid_uid,
            page_uid=page_uid,
            owning_surface=owning_surface,
            affected_resources=tuple(sorted(set(affected_resources))),
            dependency_resources=tuple(sorted(set(dependency_resources))),
            base_tokens=tuple(base_tokens),
            state=LocalDraftState.PENDING,
            operation_id=operation_id or draft_type,
            runtime_generation=0,
            leases=(),
        )
        with self._lock:
            overlapping = self._overlapping_draft_locked(
                database_id,
                draft.affected_resources + draft.dependency_resources,
            )
            if overlapping is not None:
                raise ValueError(
                    "A local edit already owns one of the requested resources."
                )
            self._drafts[draft.draft_id] = draft
        return draft

    def activate(
        self,
        draft_id: str,
        leases: tuple[ResourceLock, ...],
        *,
        runtime_generation: int,
    ) -> None:
        self._set_state(
            draft_id,
            LocalDraftState.ACTIVE,
            leases,
            runtime_generation=runtime_generation,
        )

    def finish(self, draft_id: str) -> None:
        with self._lock:
            self._drafts.pop(draft_id, None)

    def get(self, draft_id: str) -> Optional[LocalDraft]:
        with self._lock:
            return self._drafts.get(draft_id)

    def base_token(
        self, database_id: str, resource: ResourceRef
    ) -> Optional[ConcurrencyToken]:
        with self._lock:
            draft = self._overlapping_draft_locked(database_id, (resource,))
            if draft is None:
                return None
            return next(
                (
                    token
                    for stored_resource, token in draft.base_tokens
                    if stored_resource.lease_identity == resource.lease_identity
                ),
                None,
            )

    def apply_local_versions(
        self,
        database_id: str,
        versions: dict[ResourceRef, ConcurrencyToken],
    ) -> None:
        with self._lock:
            for draft_id, draft in tuple(self._drafts.items()):
                if draft.database_id != database_id:
                    continue
                base_tokens = dict(draft.base_tokens)
                changed = False
                for resource, token in versions.items():
                    matching_resource = next(
                        (
                            affected
                            for affected in draft.affected_resources
                            if affected.lease_identity == resource.lease_identity
                        ),
                        None,
                    )
                    if matching_resource is not None:
                        base_tokens[matching_resource] = token
                        changed = True
                if changed:
                    self._drafts[draft_id] = replace(
                        draft,
                        base_tokens=tuple(
                            sorted(base_tokens.items(), key=lambda item: item[0])
                        ),
                    )

    def set_base_tokens(
        self,
        draft_id: str,
        base_tokens: tuple[tuple[ResourceRef, ConcurrencyToken], ...],
    ) -> None:
        with self._lock:
            draft = self._drafts.get(draft_id)
            if draft is None:
                raise ValueError("The local draft is no longer active")
            self._drafts[draft_id] = replace(
                draft,
                base_tokens=tuple(sorted(base_tokens, key=lambda item: item[0])),
            )

    def conflicts_for_changes(
        self, database_id: str, changes: tuple[DatabaseChange, ...]
    ) -> tuple[LocalDraftConflict, ...]:
        conflicts = []
        seen = set()
        with self._lock:
            for change in changes:
                for draft_id, draft in self._drafts.items():
                    if draft.database_id != database_id:
                        continue
                    resource_identities = frozenset(
                        resource.lease_identity
                        for resource in (
                            draft.affected_resources + draft.dependency_resources
                        )
                    )
                    if (
                        change.resource.lease_identity not in resource_identities
                        or draft_id in seen
                    ):
                        continue
                    seen.add(draft_id)
                    self._drafts[draft_id] = replace(
                        draft, state=LocalDraftState.CONFLICTED
                    )
                    conflicts.append(
                        LocalDraftConflict(
                            draft_id=draft_id,
                            changed_resource=change.resource,
                            draft_type=draft.draft_type,
                            owning_surface=draft.owning_surface,
                        )
                    )
        return tuple(conflicts)

    def _set_state(
        self,
        draft_id: str,
        state: LocalDraftState,
        leases: tuple[ResourceLock, ...],
        *,
        runtime_generation: int,
    ) -> None:
        with self._lock:
            draft = self._drafts.get(draft_id)
            if draft is None:
                raise ValueError("The local draft is no longer active")
            self._drafts[draft_id] = replace(
                draft,
                state=state,
                leases=leases,
                runtime_generation=runtime_generation,
            )

    def _overlapping_draft_locked(
        self, database_id: str, resources: tuple[ResourceRef, ...]
    ) -> Optional[LocalDraft]:
        requested = frozenset(resource.lease_identity for resource in resources)
        return next(
            (
                draft
                for draft in self._drafts.values()
                if draft.database_id == database_id
                and requested.intersection(
                    resource.lease_identity
                    for resource in (
                        draft.affected_resources + draft.dependency_resources
                    )
                )
            ),
            None,
        )
