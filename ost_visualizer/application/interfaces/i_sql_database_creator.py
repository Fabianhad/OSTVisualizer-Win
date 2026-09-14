from dataclasses import dataclass
from typing import Callable, Protocol
from ...domain.entities.database_descriptor import (
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
)


@dataclass(frozen=True, repr=False)
class SqlDatabaseRuntimeCredentials:
    authentication_mode: SqlAuthenticationMode = SqlAuthenticationMode.WINDOWS
    username: str = ""
    password: str = ""

    def __repr__(self) -> str:
        return (
            "SqlDatabaseRuntimeCredentials("
            f"authentication_mode={self.authentication_mode!r}, "
            f"username={self.username!r}, password=<redacted>)"
        )


@dataclass(frozen=True)
class SqlDatabaseCreationResult:
    location: SqlServerDatabaseLocation
    schema_version: int


class ISqlDatabaseCreator(Protocol):
    def create_database_for_client(
        self,
        location: SqlServerDatabaseLocation,
        database_name: str,
        password: str = "",
        *,
        runtime_credentials: SqlDatabaseRuntimeCredentials,
        application_version: str,
        actor: str = "",
        progress: Callable[[str], None] | None = None,
    ) -> SqlDatabaseCreationResult: ...
    def create_database(
        self,
        location: SqlServerDatabaseLocation,
        database_name: str,
        password: str = "",
        *,
        application_version: str,
        actor: str = "",
        progress: Callable[[str], None] | None = None,
    ) -> SqlDatabaseCreationResult: ...
