from dataclasses import dataclass
from typing import List, Protocol
from ...domain.entities.database_descriptor import SqlServerDatabaseLocation


class DatabaseCatalogError(RuntimeError):
    """A safe, user-displayable database discovery failure."""


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
