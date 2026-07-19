from __future__ import annotations
from typing import Optional
from ...application.dtos.collaboration_resource_catalog import (
    COLLABORATION_RESOURCE_CATALOG_CHECKSUM,
)
from ...application.interfaces.i_credential_store import ICredentialStore
from ...application.interfaces.i_database_descriptor_registry import (
    IDatabaseDescriptorRegistry,
)
from .connection_manager import SqlConnectionManager
from .client_permissions import (
    SQL_CLIENT_COLLABORATION_WRITE_TABLES,
    SQL_CLIENT_DATABASE_ROLES,
    SQL_CLIENT_PROTECTED_OSTV_TABLES,
    SQL_CLIENT_SCHEMA_VISIBILITY,
    SQL_CLIENT_TRANSACTION_MARKER_TABLE,
)
from .descriptor_connection import SqlDescriptorConnectionFactory
from .errors import SqlInfrastructureError
from .schema_definition import schema_record_is_current


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
                    cursor.execute(
                        "SELECT "
                        "COALESCE(IS_ROLEMEMBER(?, USER_NAME()), 0), "
                        "COALESCE(IS_ROLEMEMBER(?, USER_NAME()), 0), "
                        "COALESCE(HAS_PERMS_BY_NAME(?, N'SCHEMA', "
                        "N'VIEW DEFINITION'), 0), "
                        "COALESCE(HAS_PERMS_BY_NAME(?, N'SCHEMA', "
                        "N'VIEW DEFINITION'), 0)",
                        *SQL_CLIENT_DATABASE_ROLES,
                        *SQL_CLIENT_SCHEMA_VISIBILITY,
                    )
                    role_row = cursor.fetchone()
                    if role_row is None or any(int(value) != 1 for value in role_row):
                        return False
                    cursor.execute(
                        "SELECT m.[SchemaVersion], sm.[Checksum], "
                        "DATABASEPROPERTYEX(DB_NAME(), N'Updateability'), "
                        "m.[WriterMode], a.[AdapterState], "
                        "a.[ResourceCatalogChecksum], "
                        "CASE WHEN EXISTS (SELECT 1 FROM "
                        "sys.change_tracking_databases WHERE database_id=DB_ID()) "
                        "THEN 1 ELSE 0 END, "
                        "CASE WHEN EXISTS (SELECT 1 FROM sys.change_tracking_tables "
                        "WHERE object_id=OBJECT_ID(N'ostv.ChangeTransactions')) "
                        "THEN 1 ELSE 0 END "
                        "FROM [ostv].[DatabaseMetadata] m "
                        "JOIN [ostv].[SchemaMigrations] sm "
                        "ON sm.[Version]=m.[SchemaVersion] "
                        "JOIN [ostv].[ExternalAdapterState] a "
                        "ON a.[SingletonId]=1"
                    )
                    row = cursor.fetchone()
                    writable_placeholders = ", ".join(
                        "?" for _ in SQL_CLIENT_COLLABORATION_WRITE_TABLES
                    )
                    protected_placeholders = ", ".join(
                        "?" for _ in SQL_CLIENT_PROTECTED_OSTV_TABLES
                    )
                    cursor.execute(
                        "SELECT "
                        f"COALESCE(SUM(CASE WHEN t.[name] IN ({writable_placeholders}) "
                        "THEN 1 ELSE 0 END), 0), "
                        "COALESCE(SUM(CASE WHEN "
                        f"t.[name] IN ({writable_placeholders}) AND NOT ("
                        "COALESCE(HAS_PERMS_BY_NAME(N'ostv.' + QUOTENAME(t.[name]), "
                        "N'OBJECT', N'SELECT'), 0)=1 AND "
                        "COALESCE(HAS_PERMS_BY_NAME(N'ostv.' + QUOTENAME(t.[name]), "
                        "N'OBJECT', N'INSERT'), 0)=1 AND "
                        "COALESCE(HAS_PERMS_BY_NAME(N'ostv.' + QUOTENAME(t.[name]), "
                        "N'OBJECT', N'UPDATE'), 0)=1 AND "
                        "COALESCE(HAS_PERMS_BY_NAME(N'ostv.' + QUOTENAME(t.[name]), "
                        "N'OBJECT', N'DELETE'), 0)=1) THEN 1 ELSE 0 END), 0), "
                        "COALESCE(SUM(CASE WHEN "
                        f"t.[name] IN ({protected_placeholders}) AND ("
                        "COALESCE(HAS_PERMS_BY_NAME(N'ostv.' + QUOTENAME(t.[name]), "
                        "N'OBJECT', N'INSERT'), 0)=1 OR "
                        "COALESCE(HAS_PERMS_BY_NAME(N'ostv.' + QUOTENAME(t.[name]), "
                        "N'OBJECT', N'UPDATE'), 0)=1 OR "
                        "COALESCE(HAS_PERMS_BY_NAME(N'ostv.' + QUOTENAME(t.[name]), "
                        "N'OBJECT', N'DELETE'), 0)=1) THEN 1 ELSE 0 END), 0) "
                        "FROM sys.tables t JOIN sys.schemas s ON "
                        "s.[schema_id]=t.[schema_id] WHERE s.[name]=N'ostv' "
                        f"AND t.[name] IN ({writable_placeholders}, "
                        f"{protected_placeholders})",
                        *SQL_CLIENT_COLLABORATION_WRITE_TABLES,
                        *SQL_CLIENT_COLLABORATION_WRITE_TABLES,
                        *SQL_CLIENT_PROTECTED_OSTV_TABLES,
                        *SQL_CLIENT_COLLABORATION_WRITE_TABLES,
                        *SQL_CLIENT_PROTECTED_OSTV_TABLES,
                    )
                    collaboration_row = cursor.fetchone()
                    marker_name = "N'ostv.' + QUOTENAME(?)"
                    cursor.execute(
                        "SELECT "
                        f"COALESCE(HAS_PERMS_BY_NAME({marker_name}, N'OBJECT', "
                        "N'SELECT'), 0), "
                        f"COALESCE(HAS_PERMS_BY_NAME({marker_name}, N'OBJECT', "
                        "N'INSERT'), 0), "
                        f"COALESCE(HAS_PERMS_BY_NAME({marker_name}, N'OBJECT', "
                        "N'UPDATE'), 0), "
                        f"COALESCE(HAS_PERMS_BY_NAME({marker_name}, N'OBJECT', "
                        "N'DELETE'), 0), "
                        f"COALESCE(HAS_PERMS_BY_NAME({marker_name}, N'OBJECT', "
                        "N'VIEW CHANGE TRACKING'), 0)",
                        *(SQL_CLIENT_TRANSACTION_MARKER_TABLE for _ in range(5)),
                    )
                    marker_row = cursor.fetchone()
        except SqlInfrastructureError:
            return False
        return bool(
            row is not None
            and schema_record_is_current(row[0], row[1])
            and str(row[2]).casefold() == "read_write"
            and int(row[6]) == 1
            and int(row[7]) == 1
            and (
                str(row[3]) == "ost_visualizer_only"
                or (
                    str(row[3]) == "mixed_application"
                    and str(row[4]) == "validated"
                    and str(row[5]) == COLLABORATION_RESOURCE_CATALOG_CHECKSUM
                )
            )
            and collaboration_row is not None
            and int(collaboration_row[0]) == len(SQL_CLIENT_COLLABORATION_WRITE_TABLES)
            and int(collaboration_row[1]) == 0
            and int(collaboration_row[2]) == 0
            and marker_row is not None
            and tuple(int(value) for value in marker_row) == (1, 1, 0, 0, 1)
        )
