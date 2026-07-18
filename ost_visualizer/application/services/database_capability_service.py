from __future__ import annotations
from ..interfaces.i_database_catalog import DatabaseCatalogError
from ..interfaces.i_database_descriptor_registry import IDatabaseDescriptorRegistry
from ..interfaces.i_database_permission_probe import IDatabasePermissionProbe
from ...domain.entities.database_descriptor import DatabaseBackend


class DatabaseCapabilityService:
    """Authoritative database editability state projected by the UI."""

    def __init__(
        self,
        descriptor_registry: IDatabaseDescriptorRegistry,
        permission_probe: IDatabasePermissionProbe,
    ) -> None:
        self._registry = descriptor_registry
        self._permission_probe = permission_probe
        self._editable_sql_databases: set[str] = set()

    def mark_connected(self, database_id: str) -> None:
        descriptor = self._registry.resolve(database_id)
        if descriptor is None or descriptor.backend == DatabaseBackend.ACCESS:
            return
        try:
            editable = self._permission_probe.can_edit(database_id)
        except (DatabaseCatalogError, OSError):
            editable = False
        if editable:
            self._editable_sql_databases.add(database_id)
        else:
            self._editable_sql_databases.discard(database_id)

    def mark_disconnected(self, database_id: str) -> None:
        self._editable_sql_databases.discard(database_id)

    def is_editable(self, locator: str) -> bool:
        descriptor = self._registry.resolve(locator)
        if descriptor is None:
            return False
        if descriptor.backend == DatabaseBackend.ACCESS:
            return True
        return descriptor.database_id in self._editable_sql_databases
