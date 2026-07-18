from typing import Protocol
from ..dtos.collaboration_dtos import ConcurrencyToken, ResourceRef


class IEntityVersionReader(Protocol):
    def read_database_versions(
        self, database_id: str
    ) -> dict[ResourceRef, ConcurrencyToken]: ...
    def read_bid_versions(
        self, database_id: str, bid_uid: str
    ) -> dict[ResourceRef, ConcurrencyToken]: ...
