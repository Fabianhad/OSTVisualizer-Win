from ...application.interfaces.i_database_maintenance import DatabaseMaintenanceResult
from ...shared.texts import (
    DATABASE_MAINTENANCE_MESSAGE_COMPACT_REPAIR_IS_NOT_AVAILABLE_FOR,
)


class SqlDatabaseMaintenance:
    def unavailable_reason(self, locator: str) -> str:
        return DATABASE_MAINTENANCE_MESSAGE_COMPACT_REPAIR_IS_NOT_AVAILABLE_FOR

    def capture_target(self, locator: str):
        raise RuntimeError(self.unavailable_reason(locator))

    def prepare(self, locator: str, identity: object):
        raise RuntimeError(self.unavailable_reason(locator))

    def is_target_current(self, locator: str, identity: object) -> bool:
        return False

    def release_target(self, locator: str, identity: object) -> None:
        raise RuntimeError(self.unavailable_reason(locator))

    def compact(self, locator: str) -> DatabaseMaintenanceResult:
        return DatabaseMaintenanceResult(False, self.unavailable_reason(locator))
