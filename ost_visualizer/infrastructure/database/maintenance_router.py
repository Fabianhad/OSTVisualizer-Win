from ...domain.entities.database_descriptor import DatabaseBackend
from .descriptor_registry import resolve_database_backend


class DatabaseMaintenanceRouter:
    def __init__(self, registry, access, sql):
        self._registry = registry
        self._backends = {
            DatabaseBackend.ACCESS: access,
            DatabaseBackend.SQL_SERVER: sql,
        }

    def _backend(self, locator):
        return self._backends[resolve_database_backend(self._registry, locator)]

    def capture_target(self, locator: str):
        return self._backend(locator).capture_target(locator)

    def prepare(self, locator: str, identity: object):
        return self._backend(locator).prepare(locator, identity)

    def unavailable_reason(self, locator: str) -> str:
        return self._backend(locator).unavailable_reason(locator)

    def compact(self, locator: str):
        return self._backend(locator).compact(locator)
