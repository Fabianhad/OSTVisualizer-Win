from __future__ import annotations
from typing import Protocol
from ..dtos.collaboration_dtos import (
    DatabaseChangeBatch,
    HydratedDatabaseChangeBatch,
)


class IRemoteChangeReader(Protocol):
    def initial_reconciliation(
        self, database_id: str, bid_uid: int | None, checkpoint: int
    ) -> HydratedDatabaseChangeBatch: ...
    def hydrate(self, batch: DatabaseChangeBatch) -> HydratedDatabaseChangeBatch: ...
