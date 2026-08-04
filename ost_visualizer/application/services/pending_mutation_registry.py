from __future__ import annotations
import threading
from dataclasses import replace
from typing import Optional
from ..dtos.collaboration_dtos import (
    PendingMutation,
    PendingMutationState,
    QueuedMutationRequest,
)

_ALLOWED_TRANSITIONS = {
    PendingMutationState.QUEUED: frozenset(
        {
            PendingMutationState.EXECUTING,
            PendingMutationState.RECOVERING,
        }
    ),
    PendingMutationState.EXECUTING: frozenset(
        {
            PendingMutationState.PROJECTING,
            PendingMutationState.RECOVERING,
            PendingMutationState.UNCERTAIN,
        }
    ),
    PendingMutationState.PROJECTING: frozenset(
        {
            PendingMutationState.RECOVERING,
            PendingMutationState.UNCERTAIN,
        }
    ),
    PendingMutationState.RECOVERING: frozenset(
        {
            PendingMutationState.PROJECTING,
            PendingMutationState.UNCERTAIN,
        }
    ),
    PendingMutationState.UNCERTAIN: frozenset(
        {
            PendingMutationState.RECOVERING,
            PendingMutationState.PROJECTING,
        }
    ),
}


class PendingMutationRegistry:
    def __init__(self) -> None:
        self._mutations: dict[str, PendingMutation] = {}
        self._lock = threading.Lock()

    def begin(
        self,
        request: QueuedMutationRequest,
        *,
        runtime_generation: int = 0,
    ) -> PendingMutation:
        pending = PendingMutation(
            request=request,
            runtime_generation=runtime_generation,
        )
        with self._lock:
            if request.operation_id in self._mutations:
                raise ValueError("A pending mutation already uses this operation ID")
            self._mutations[request.operation_id] = pending
        return pending

    def transition(
        self,
        operation_id: str,
        state: PendingMutationState,
        *,
        runtime_generation: Optional[int] = None,
        message: Optional[str] = None,
    ) -> PendingMutation:
        with self._lock:
            pending = self._mutations.get(operation_id)
            if pending is None:
                raise ValueError("The pending mutation is no longer registered")
            if (
                state != pending.state
                and state not in _ALLOWED_TRANSITIONS[pending.state]
            ):
                raise ValueError(
                    f"Invalid pending mutation transition: {pending.state.value} -> "
                    f"{state.value}"
                )
            pending = replace(
                pending,
                state=state,
                runtime_generation=(
                    pending.runtime_generation
                    if runtime_generation is None
                    else runtime_generation
                ),
                message=pending.message if message is None else message,
            )
            self._mutations[operation_id] = pending
            return pending

    def finish(self, operation_id: str) -> Optional[PendingMutation]:
        with self._lock:
            return self._mutations.pop(operation_id, None)

    def get(self, operation_id: str) -> Optional[PendingMutation]:
        with self._lock:
            return self._mutations.get(operation_id)

    def for_database(self, database_id: str) -> tuple[PendingMutation, ...]:
        with self._lock:
            return tuple(
                pending
                for pending in self._mutations.values()
                if pending.request.database_id == database_id
            )

    def clear_database(self, database_id: str) -> tuple[PendingMutation, ...]:
        with self._lock:
            operation_ids = tuple(
                operation_id
                for operation_id, pending in self._mutations.items()
                if pending.request.database_id == database_id
            )
            return tuple(
                self._mutations.pop(operation_id) for operation_id in operation_ids
            )
