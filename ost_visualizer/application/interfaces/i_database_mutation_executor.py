from __future__ import annotations
from typing import Callable, Protocol, TypeVar
from ..dtos.collaboration_dtos import (
    ChangeOperation,
    DatabaseMutationRequest,
    DatabaseMutationResult,
    ResourceRef,
)

T = TypeVar("T")


class IMutationRecorder(Protocol):
    def record(
        self,
        resource: ResourceRef,
        operation: ChangeOperation,
        *,
        changed_fields: tuple[str, ...] = (),
        payload: str = "",
    ) -> None: ...
class IDatabaseMutationExecutor(Protocol):
    def execute(
        self,
        request: DatabaseMutationRequest,
        operation: Callable[[IMutationRecorder], T],
    ) -> DatabaseMutationResult[T]: ...
