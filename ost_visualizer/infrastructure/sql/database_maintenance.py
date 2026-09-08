from ...application.interfaces.i_database_maintenance import DatabaseMaintenanceResult


class SqlDatabaseMaintenance:
    def unavailable_reason(self, locator: str) -> str:
        return (
            "Compact/Repair is not available for SQL Server. SQL Server manages space "
            "differently; OST Visualizer will not shrink databases or remove collaboration history."
        )

    def capture_target(self, locator: str):
        raise RuntimeError(self.unavailable_reason(locator))

    def prepare(self, locator: str, identity: object):
        raise RuntimeError(self.unavailable_reason(locator))

    def compact(self, locator: str) -> DatabaseMaintenanceResult:
        return DatabaseMaintenanceResult(False, self.unavailable_reason(locator))
