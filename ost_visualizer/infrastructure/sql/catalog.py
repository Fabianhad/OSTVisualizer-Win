from __future__ import annotations
from typing import List, Optional
from ...application.interfaces.i_database_catalog import (
    DatabaseCatalogError,
    SqlDatabaseCatalogEntry,
)
from ...domain.entities.database_descriptor import SqlServerDatabaseLocation
from .connection_manager import SqlConnectionManager, SqlConnectionRequest
from .schema_inspector import SqlSchemaInspector
from .schema_definition import LATEST_SQL_SCHEMA
from .schema_validator import SqlSchemaValidator


class SqlDatabaseCatalog:
    def __init__(
        self,
        connection_manager: Optional[SqlConnectionManager] = None,
    ):
        self._connections = connection_manager or SqlConnectionManager()
        self._inspector = SqlSchemaInspector(self._connections)
        self._validator = SqlSchemaValidator(LATEST_SQL_SCHEMA.core_schema)

    def list_databases(
        self, location: SqlServerDatabaseLocation, password: str = ""
    ) -> List[SqlDatabaseCatalogEntry]:
        request = SqlConnectionRequest(
            location=location,
            password=password,
            database_override="master",
            read_only=True,
        )
        with self._connections.connection(request, autocommit=True) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    "SELECT [name], [state_desc], HAS_DBACCESS([name]) "
                    "FROM sys.databases WHERE database_id > 4 ORDER BY [name]"
                )
                databases = [tuple(row) for row in cursor.fetchall()]
        result: List[SqlDatabaseCatalogEntry] = []
        for name, state, access in databases:
            try:
                result.append(
                    self._inspect_database(
                        location, password, name, state, bool(access)
                    )
                )
            except DatabaseCatalogError:
                result.append(
                    SqlDatabaseCatalogEntry(
                        name=name,
                        database_guid="",
                        state=state,
                        is_compatible=False,
                        compatibility_message=(
                            "This database could not be inspected with the current "
                            "login."
                        ),
                    )
                )
        return result

    def get_database(
        self,
        location: SqlServerDatabaseLocation,
        database_name: str,
        password: str = "",
    ) -> SqlDatabaseCatalogEntry:
        request = SqlConnectionRequest(
            location=location,
            password=password,
            database_override="master",
            read_only=True,
        )
        with self._connections.connection(request, autocommit=True) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    "SELECT [name], [state_desc], HAS_DBACCESS([name]) "
                    "FROM sys.databases WHERE database_id > 4 AND [name]=?",
                    database_name,
                )
                row = cursor.fetchone()
        if row is None:
            raise DatabaseCatalogError(
                "The selected database is no longer available to this login."
            )
        return self._inspect_database(
            location,
            password,
            str(row[0]),
            str(row[1]),
            bool(row[2]),
        )

    def _inspect_database(
        self,
        location: SqlServerDatabaseLocation,
        password: str,
        name: str,
        state: str,
        has_access: bool,
    ) -> SqlDatabaseCatalogEntry:
        if state != "ONLINE" or not has_access:
            return SqlDatabaseCatalogEntry(
                name=name,
                database_guid="",
                state=state,
                is_compatible=False,
                compatibility_message="Database is not available to this login.",
            )
        inventory = self._inspector.inspect(location, password, database_override=name)
        report = self._validator.validate(inventory)
        if report.is_read_compatible and not self._can_read_bids(
            location, password, name
        ):
            return SqlDatabaseCatalogEntry(
                name=name,
                database_guid=inventory.database_guid,
                state=state,
                is_compatible=False,
                compatibility_message=(
                    "The current login does not have permission to read bids in "
                    "this database."
                ),
                schema_version=inventory.schema_version,
            )
        return SqlDatabaseCatalogEntry(
            name=name,
            database_guid=inventory.database_guid,
            state=state,
            is_compatible=report.is_read_compatible,
            compatibility_message=report.user_message,
            schema_version=inventory.schema_version,
        )

    def _can_read_bids(
        self,
        location: SqlServerDatabaseLocation,
        password: str,
        database_name: str,
    ) -> bool:
        request = SqlConnectionRequest(
            location=location,
            password=password,
            database_override=database_name,
            read_only=True,
        )
        with self._connections.connection(request, autocommit=True) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    "SELECT HAS_PERMS_BY_NAME(N'dbo.Bids', N'OBJECT', N'SELECT')"
                )
                row = cursor.fetchone()
        return bool(row is not None and row[0])
