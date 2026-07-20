from __future__ import annotations
from typing import Optional
from ...application.interfaces.i_credential_store import ICredentialStore
from ...application.interfaces.i_database_descriptor_registry import (
    IDatabaseDescriptorRegistry,
)
from .client_permissions import require_sql_client_editability
from .connection_manager import SqlConnectionManager
from .descriptor_connection import SqlDescriptorConnectionFactory
from .errors import SqlInfrastructureError


class SqlDatabasePermissionProbe:
    def __init__(
        self,
        descriptor_registry: IDatabaseDescriptorRegistry,
        credential_store: ICredentialStore,
        connection_manager: Optional[SqlConnectionManager] = None,
    ) -> None:
        self._requests = SqlDescriptorConnectionFactory(
            descriptor_registry, credential_store
        )
        self._connections = connection_manager or SqlConnectionManager()

    def can_edit(self, database_id: str) -> bool:
        try:
            request = self._requests.request(database_id, read_only=True)
            with self._connections.connection(request, autocommit=True) as lease:
                with lease.cursor() as cursor:
                    require_sql_client_editability(cursor)
        except SqlInfrastructureError:
            return False
        return True
