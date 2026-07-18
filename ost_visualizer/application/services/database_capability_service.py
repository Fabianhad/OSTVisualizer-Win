from __future__ import annotations
from ..dtos.collaboration_dtos import (
    CollaborationStatus,
    ResourceRef,
    SynchronizationState,
)
from ..interfaces.i_database_catalog import DatabaseCatalogError
from ..interfaces.i_database_descriptor_registry import IDatabaseDescriptorRegistry
from ..interfaces.i_database_permission_probe import IDatabasePermissionProbe
from ...domain.entities.database_descriptor import DatabaseBackend


class DatabaseCapabilityService:
    def __init__(
        self,
        descriptor_registry: IDatabaseDescriptorRegistry,
        permission_probe: IDatabasePermissionProbe,
    ) -> None:
        self._registry = descriptor_registry
        self._permission_probe = permission_probe
        self._permission_editable_sql_databases: set[str] = set()
        self._collaboration_statuses: dict[str, CollaborationStatus] = {}

    def mark_connected(self, database_id: str) -> None:
        descriptor = self._registry.resolve(database_id)
        if descriptor is None or descriptor.backend == DatabaseBackend.ACCESS:
            return
        try:
            editable = self._permission_probe.can_edit(database_id)
        except (DatabaseCatalogError, OSError):
            editable = False
        if editable:
            self._permission_editable_sql_databases.add(database_id)
        else:
            self._permission_editable_sql_databases.discard(database_id)

    def mark_disconnected(self, database_id: str) -> None:
        self._permission_editable_sql_databases.discard(database_id)
        self._collaboration_statuses.pop(database_id, None)

    def set_collaboration_state(
        self,
        database_id: str,
        state: SynchronizationState,
        message: str = "",
    ) -> None:
        descriptor = self._registry.resolve(database_id)
        if descriptor is None or descriptor.backend != DatabaseBackend.SQL_SERVER:
            return
        current = self._collaboration_statuses.get(database_id)
        self._collaboration_statuses[database_id] = CollaborationStatus(
            database_id=database_id,
            state=state,
            message=message,
            locked_resources=(
                current.locked_resources if current is not None else frozenset()
            ),
            conflicted_resources=(
                current.conflicted_resources if current is not None else frozenset()
            ),
        )

    def collaboration_status(self, database_id: str) -> CollaborationStatus:
        return self._collaboration_statuses.get(
            database_id,
            CollaborationStatus(
                database_id=database_id,
                state=SynchronizationState.STOPPED,
            ),
        )

    def update_collaboration_resources(
        self,
        database_id: str,
        locked_resources: frozenset[ResourceRef],
        conflicted_resources: frozenset[ResourceRef] = frozenset(),
    ) -> None:
        current = self.collaboration_status(database_id)
        self._collaboration_statuses[database_id] = CollaborationStatus(
            database_id=database_id,
            state=current.state,
            message=current.message,
            locked_resources=locked_resources,
            conflicted_resources=conflicted_resources,
        )

    def add_collaboration_conflict(
        self, database_id: str, resource: ResourceRef
    ) -> None:
        current = self.collaboration_status(database_id)
        self.update_collaboration_resources(
            database_id,
            current.locked_resources,
            current.conflicted_resources | frozenset({resource}),
        )

    def clear_collaboration_conflicts(self, database_id: str) -> None:
        current = self.collaboration_status(database_id)
        if current.conflicted_resources:
            self.update_collaboration_resources(database_id, current.locked_resources)

    def is_editable(self, locator: str, resource: ResourceRef | None = None) -> bool:
        descriptor = self._registry.resolve(locator)
        if descriptor is None:
            return False
        if descriptor.backend == DatabaseBackend.ACCESS:
            return True
        editable = (
            descriptor.database_id in self._permission_editable_sql_databases
            and self.collaboration_status(descriptor.database_id).state
            == SynchronizationState.HEALTHY
        )
        if not editable or resource is None:
            return editable
        status = self.collaboration_status(descriptor.database_id)
        blocked = status.locked_resources | status.conflicted_resources
        return not any(
            (
                candidate.resource_type == resource.resource_type
                and candidate.resource_id == resource.resource_id
            )
            or (
                resource.resource_type == "bid"
                and resource.bid_uid is not None
                and candidate.bid_uid == resource.bid_uid
            )
            or (
                candidate.resource_type == "bid"
                and resource.bid_uid is not None
                and candidate.resource_id == str(resource.bid_uid)
            )
            for candidate in blocked
        )
