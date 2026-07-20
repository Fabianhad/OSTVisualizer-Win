from __future__ import annotations
from typing import Optional
from ...application.dtos.collaboration_dtos import ConcurrencyToken, ResourceRef
from ...application.interfaces.i_credential_store import ICredentialStore
from ...application.interfaces.i_database_descriptor_registry import (
    IDatabaseDescriptorRegistry,
)
from ...application.interfaces.i_entity_version_reader import IEntityVersionReader
from ...domain.entities.database_descriptor import DatabaseBackend
from ..sql.connection_manager import SqlConnectionManager
from ..sql.descriptor_connection import SqlDescriptorConnectionFactory
from ..sql.schema_definition import SQL_SCHEMA_V1


class DatabaseEntityVersionReader(IEntityVersionReader):
    def __init__(
        self,
        descriptor_registry: IDatabaseDescriptorRegistry,
        credential_store: ICredentialStore,
        connection_manager: Optional[SqlConnectionManager] = None,
    ) -> None:
        self._registry = descriptor_registry
        self._requests = SqlDescriptorConnectionFactory(
            descriptor_registry, credential_store
        )
        self._connections = connection_manager or SqlConnectionManager()

    def read_database_versions(
        self, database_id: str
    ) -> dict[ResourceRef, ConcurrencyToken]:
        return self._read_versions(database_id, None)

    def read_bid_versions(
        self, database_id: str, bid_uid: str
    ) -> dict[ResourceRef, ConcurrencyToken]:
        return self._read_versions(database_id, int(bid_uid))

    def _read_versions(
        self, database_id: str, bid_uid: Optional[int]
    ) -> dict[ResourceRef, ConcurrencyToken]:
        descriptor = self._registry.resolve(database_id)
        if (
            descriptor is None
            or descriptor.backend != DatabaseBackend.SQL_SERVER
            or descriptor.schema_version != SQL_SCHEMA_V1.version
        ):
            return {}
        request = self._requests.request(database_id, read_only=True)
        with self._connections.connection(request, autocommit=True) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    "SELECT [ResourceType], [ResourceId], [BidUID], [Token] "
                    "FROM [ostv].[EntityVersions] WHERE "
                    "(? IS NULL AND [BidUID] IS NULL) OR [BidUID]=?",
                    bid_uid,
                    bid_uid,
                )
                rows = cursor.fetchall()
        return {
            ResourceRef(
                str(row[0]),
                str(row[1]),
                int(row[2]) if row[2] is not None else None,
            ): (ConcurrencyToken.from_database(row[3]))
            for row in rows
        }
