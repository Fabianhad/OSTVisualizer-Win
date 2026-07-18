from __future__ import annotations
from typing import Optional
from ...application.interfaces.i_credential_store import ICredentialStore
from ...application.interfaces.i_database_descriptor_registry import (
    IDatabaseDescriptorRegistry,
)
from .connection_manager import SqlConnectionManager
from .descriptor_connection import SqlDescriptorConnectionFactory
from .errors import SqlInfrastructureError
from .schema_definition import LATEST_SQL_SCHEMA, schema_record_is_current


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
                    table_names = tuple(
                        table.name for table in LATEST_SQL_SCHEMA.core_schema.tables
                    )
                    placeholders = ", ".join("?" for _ in table_names)
                    cursor.execute(
                        "SELECT COUNT_BIG(*), "
                        "COALESCE(SUM(CASE WHEN "
                        "COALESCE(HAS_PERMS_BY_NAME(QUOTENAME(s.[name]) + N'.' + "
                        "QUOTENAME(t.[name]), N'OBJECT', N'SELECT'), 0)=1 AND "
                        "COALESCE(HAS_PERMS_BY_NAME(QUOTENAME(s.[name]) + N'.' + "
                        "QUOTENAME(t.[name]), N'OBJECT', N'INSERT'), 0)=1 AND "
                        "COALESCE(HAS_PERMS_BY_NAME(QUOTENAME(s.[name]) + N'.' + "
                        "QUOTENAME(t.[name]), N'OBJECT', N'UPDATE'), 0)=1 AND "
                        "COALESCE(HAS_PERMS_BY_NAME(QUOTENAME(s.[name]) + N'.' + "
                        "QUOTENAME(t.[name]), N'OBJECT', N'DELETE'), 0)=1 "
                        "THEN 0 ELSE 1 END), 0) "
                        "FROM sys.tables t JOIN sys.schemas s "
                        "ON s.[schema_id]=t.[schema_id] "
                        f"WHERE s.[name]=N'dbo' AND t.[name] IN ({placeholders})",
                        *table_names,
                    )
                    permission_row = cursor.fetchone()
                    if (
                        permission_row is None
                        or int(permission_row[0]) != len(table_names)
                        or int(permission_row[1]) != 0
                    ):
                        return False
                    cursor.execute(
                        "SELECT m.[SchemaVersion], sm.[Checksum], "
                        "DATABASEPROPERTYEX(DB_NAME(), N'Updateability') "
                        "FROM [ostv].[DatabaseMetadata] m "
                        "JOIN [ostv].[SchemaMigrations] sm "
                        "ON sm.[Version]=m.[SchemaVersion]"
                    )
                    row = cursor.fetchone()
                    collaboration_tables = (
                        "Sessions",
                        "Presence",
                        "Locks",
                        "EntityVersions",
                        "ChangeLog",
                        "ChangeFeedState",
                    )
                    collaboration_placeholders = ", ".join(
                        "?" for _ in collaboration_tables
                    )
                    cursor.execute(
                        "SELECT COUNT_BIG(*), COALESCE(SUM(CASE WHEN "
                        "COALESCE(HAS_PERMS_BY_NAME(N'ostv.' + QUOTENAME(t.[name]), "
                        "N'OBJECT', N'SELECT'), 0)=1 AND "
                        "COALESCE(HAS_PERMS_BY_NAME(N'ostv.' + QUOTENAME(t.[name]), "
                        "N'OBJECT', N'INSERT'), 0)=1 AND "
                        "COALESCE(HAS_PERMS_BY_NAME(N'ostv.' + QUOTENAME(t.[name]), "
                        "N'OBJECT', N'UPDATE'), 0)=1 AND "
                        "COALESCE(HAS_PERMS_BY_NAME(N'ostv.' + QUOTENAME(t.[name]), "
                        "N'OBJECT', N'DELETE'), 0)=1 THEN 0 ELSE 1 END), 0) "
                        "FROM sys.tables t JOIN sys.schemas s ON "
                        "s.[schema_id]=t.[schema_id] WHERE s.[name]=N'ostv' "
                        f"AND t.[name] IN ({collaboration_placeholders})",
                        *collaboration_tables,
                    )
                    collaboration_row = cursor.fetchone()
        except SqlInfrastructureError:
            return False
        return bool(
            row is not None
            and schema_record_is_current(row[0], row[1])
            and str(row[2]).casefold() == "read_write"
            and collaboration_row is not None
            and int(collaboration_row[0]) == len(collaboration_tables)
            and int(collaboration_row[1]) == 0
        )
