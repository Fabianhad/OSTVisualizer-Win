from dataclasses import dataclass
from typing import List, Protocol
from ...domain.entities.database_descriptor import SqlServerDatabaseLocation


class DatabaseCatalogError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        session_expired: bool = False,
        credential_required: bool = False,
        read_only_required: bool = False,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.session_expired = session_expired
        self.credential_required = credential_required
        self.read_only_required = read_only_required


@dataclass(frozen=True)
class SqlDatabaseCatalogEntry:
    name: str
    database_guid: str
    state: str
    is_compatible: bool
    compatibility_message: str = ""
    schema_version: int = 0


class IDatabaseCatalog(Protocol):
    def list_databases(
        self, location: SqlServerDatabaseLocation, password: str = ""
    ) -> List[SqlDatabaseCatalogEntry]: ...
    def get_database(
        self,
        location: SqlServerDatabaseLocation,
        database_name: str,
        password: str = "",
    ) -> SqlDatabaseCatalogEntry: ...
