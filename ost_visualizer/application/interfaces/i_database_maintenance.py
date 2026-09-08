from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DatabaseMaintenanceResult:
    success: bool
    message: str


class IPreparedDatabaseMaintenance(Protocol):
    def commit(self) -> DatabaseMaintenanceResult: ...
    def close(self) -> None: ...
class IDatabaseMaintenance(Protocol):
    def capture_target(self, locator: str) -> object: ...
    def prepare(
        self, locator: str, identity: object
    ) -> IPreparedDatabaseMaintenance: ...
    def unavailable_reason(self, locator: str) -> str: ...
    def compact(self, locator: str) -> DatabaseMaintenanceResult: ...
