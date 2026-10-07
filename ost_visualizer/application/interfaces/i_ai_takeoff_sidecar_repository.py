from typing import Protocol
from ...domain.entities.ai_takeoff import SidecarLoad


class IAiTakeoffSidecarRepository(Protocol):
    def load(self, bid_key: str) -> SidecarLoad: ...
