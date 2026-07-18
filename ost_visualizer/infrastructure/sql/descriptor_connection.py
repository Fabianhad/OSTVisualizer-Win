from __future__ import annotations
from ...application.interfaces.i_credential_store import ICredentialStore
from ...application.interfaces.i_database_descriptor_registry import (
    IDatabaseDescriptorRegistry,
)
from ...domain.entities.database_descriptor import (
    DatabaseBackend,
    SqlAuthenticationMode,
    credential_target_for,
)
from .connection_manager import SqlConnectionRequest
from .errors import SqlErrorCode, SqlErrorDetails, SqlInfrastructureError


class SqlDescriptorConnectionFactory:
    def __init__(
        self,
        descriptor_registry: IDatabaseDescriptorRegistry,
        credential_store: ICredentialStore,
    ) -> None:
        self._descriptor_registry = descriptor_registry
        self._credential_store = credential_store

    def request(self, database_id: str, *, read_only: bool) -> SqlConnectionRequest:
        descriptor = self._descriptor_registry.resolve(database_id)
        if descriptor is None or descriptor.backend != DatabaseBackend.SQL_SERVER:
            raise SqlInfrastructureError(
                SqlErrorDetails(
                    SqlErrorCode.DATABASE_MISSING,
                    "The saved SQL Server database connection was not found.",
                )
            )
        location = descriptor.sql_location
        password = ""
        if location.authentication_mode == SqlAuthenticationMode.SQL_SERVER:
            stored_password = self._credential_store.read_password(
                credential_target_for(descriptor.database_id)
            )
            if stored_password is None or stored_password == "":
                raise SqlInfrastructureError(
                    SqlErrorDetails(
                        SqlErrorCode.CREDENTIAL_MISSING,
                        "The saved SQL Server credential is missing. Reconnect to "
                        "this database and enter the password again.",
                    )
                )
            password = stored_password
        return SqlConnectionRequest(location, password, read_only=read_only)
