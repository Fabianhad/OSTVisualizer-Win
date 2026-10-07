from typing import Protocol
from ...domain.entities.ai_takeoff import AiTakeoffSidecar, SidecarLoad


class IAiTakeoffSidecarRepository(Protocol):
    def load(self, bid_key: str) -> SidecarLoad: ...
    def save(self, sidecar: AiTakeoffSidecar) -> None: ...
