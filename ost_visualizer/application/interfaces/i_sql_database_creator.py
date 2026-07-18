from dataclasses import dataclass
from typing import Protocol
from ...domain.entities.database_descriptor import SqlServerDatabaseLocation


@dataclass(frozen=True)
class SqlDatabaseCreationResult:
    location: SqlServerDatabaseLocation
    schema_version: int


class ISqlDatabaseCreator(Protocol):
    def can_create_database(
        self, location: SqlServerDatabaseLocation, password: str = ""
    ) -> bool: ...
    def create_database(
        self,
        location: SqlServerDatabaseLocation,
        database_name: str,
        password: str = "",
        *,
        application_version: str,
        actor: str = "",
    ) -> SqlDatabaseCreationResult: ...
    def initialize_compatible_database(
        self,
        location: SqlServerDatabaseLocation,
        password: str = "",
        *,
        application_version: str,
        actor: str = "",
    ) -> SqlDatabaseCreationResult: ...
