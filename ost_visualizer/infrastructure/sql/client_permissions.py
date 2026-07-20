from __future__ import annotations
from ...application.dtos.collaboration_resource_catalog import (
    COLLABORATION_RESOURCE_CATALOG_CHECKSUM,
)
from .errors import SqlErrorCode, SqlErrorDetails, SqlInfrastructureError
from .schema_definition import (
    SQL_SCHEMA_V1,
    SQL_CHANGE_TRACKING_RETENTION_DAYS,
    schema_record_is_canonical,
)

SQL_CLIENT_DATABASE_ROLES = ("db_datareader", "db_datawriter")
SQL_CLIENT_SCHEMA_VISIBILITY = ("dbo", "ostv")
SQL_CLIENT_COLLABORATION_WRITE_TABLES = (
    "Sessions",
    "Presence",
    "Locks",
    "EntityVersions",
    "ChangeLog",
)
SQL_CLIENT_TRANSACTION_MARKER_TABLE = "ChangeTransactions"
SQL_CLIENT_PROTECTED_OSTV_TABLES = tuple(
    table.name
    for table in SQL_SCHEMA_V1.tables
    if table.name
    not in {
        *SQL_CLIENT_COLLABORATION_WRITE_TABLES,
        SQL_CLIENT_TRANSACTION_MARKER_TABLE,
    }
)


def _sql_integer_values_match(row, expected: tuple[int, ...]) -> bool:
    if row is None:
        return False
    try:
        values = tuple(int(value) for value in row)
    except (TypeError, ValueError):
        return False
    return values == expected


def require_sql_client_editability(cursor) -> None:
    cursor.execute(
        "SELECT "
        "COALESCE(IS_ROLEMEMBER(?, USER_NAME()), 0), "
        "COALESCE(IS_ROLEMEMBER(?, USER_NAME()), 0), "
        "COALESCE(HAS_PERMS_BY_NAME(?, N'SCHEMA', N'VIEW DEFINITION'), 0), "
        "COALESCE(HAS_PERMS_BY_NAME(?, N'SCHEMA', N'VIEW DEFINITION'), 0), "
        "CASE WHEN COALESCE((SELECT p.[default_schema_name] "
        "FROM sys.database_principals p WHERE p.[name]=USER_NAME()), N'')="
        "N'dbo' THEN 1 ELSE 0 END",
        *SQL_CLIENT_DATABASE_ROLES,
        *SQL_CLIENT_SCHEMA_VISIBILITY,
    )
    role_row = cursor.fetchone()
    if not _sql_integer_values_match(role_row, (1, 1, 1, 1, 1)):
        raise SqlInfrastructureError(
            SqlErrorDetails(
                SqlErrorCode.PERMISSION_DENIED,
                "SQL editing requires the configured user to belong to the "
                "required SQL database roles, use dbo as its default schema, "
                "and have the canonical schema visibility grants.",
            )
        )
    cursor.execute(
        "SELECT m.[SchemaVersion], sm.[Checksum], "
        "DATABASEPROPERTYEX(DB_NAME(), N'Updateability'), "
        "m.[WriterMode], a.[AdapterState], a.[ResourceCatalogChecksum], "
        "CASE WHEN EXISTS (SELECT 1 FROM sys.change_tracking_databases "
        "WHERE database_id=DB_ID()) THEN 1 ELSE 0 END, "
        "CASE WHEN EXISTS (SELECT 1 FROM sys.change_tracking_tables "
        "WHERE object_id=OBJECT_ID(N'ostv.ChangeTransactions')) "
        "THEN 1 ELSE 0 END, "
        "CASE WHEN EXISTS (SELECT 1 FROM sys.databases WHERE "
        "database_id=DB_ID() AND snapshot_isolation_state=1) "
        "THEN 1 ELSE 0 END, "
        "CASE WHEN EXISTS (SELECT 1 FROM sys.change_tracking_databases "
        "WHERE database_id=DB_ID() "
        f"AND retention_period={SQL_CHANGE_TRACKING_RETENTION_DAYS} AND "
        "retention_period_units_desc=N'DAYS' AND is_auto_cleanup_on=1) "
        "THEN 1 ELSE 0 END "
        "FROM [ostv].[DatabaseMetadata] m "
        "JOIN [ostv].[SchemaMigrations] sm ON sm.[Version]=m.[SchemaVersion] "
        "JOIN [ostv].[ExternalAdapterState] a ON a.[SingletonId]=1 "
        "WHERE m.[Product]=N'OST Visualizer'"
    )
    metadata_row = cursor.fetchone()
    metadata_complete = metadata_row is not None and len(metadata_row) == 10
    writer_mode_valid = bool(
        metadata_complete
        and (
            str(metadata_row[3]) == "ost_visualizer_only"
            or (
                str(metadata_row[3]) == "mixed_application"
                and str(metadata_row[4]) == "validated"
                and str(metadata_row[5]) == COLLABORATION_RESOURCE_CATALOG_CHECKSUM
            )
        )
    )
    if (
        not metadata_complete
        or not schema_record_is_canonical(metadata_row[0], metadata_row[1])
        or str(metadata_row[2]).casefold() != "read_write"
        or not writer_mode_valid
        or not _sql_integer_values_match(
            tuple(metadata_row[index] for index in range(6, 10)),
            (1, 1, 1, 1),
        )
    ):
        raise SqlInfrastructureError(
            SqlErrorDetails(
                SqlErrorCode.SCHEMA_MISMATCH,
                "This SQL database is not writable by this OST Visualizer version.",
            )
        )
    writable_placeholders = ", ".join(
        "?" for _ in SQL_CLIENT_COLLABORATION_WRITE_TABLES
    )
    protected_placeholders = ", ".join("?" for _ in SQL_CLIENT_PROTECTED_OSTV_TABLES)
    cursor.execute(
        "SELECT "
        f"COALESCE(SUM(CASE WHEN t.[name] IN ({writable_placeholders}) "
        "THEN 1 ELSE 0 END), 0), "
        f"COALESCE(SUM(CASE WHEN t.[name] IN ({writable_placeholders}) AND NOT ("
        "COALESCE(HAS_PERMS_BY_NAME(N'ostv.' + QUOTENAME(t.[name]), "
        "N'OBJECT', N'SELECT'), 0)=1 AND "
        "COALESCE(HAS_PERMS_BY_NAME(N'ostv.' + QUOTENAME(t.[name]), "
        "N'OBJECT', N'INSERT'), 0)=1 AND "
        "COALESCE(HAS_PERMS_BY_NAME(N'ostv.' + QUOTENAME(t.[name]), "
        "N'OBJECT', N'UPDATE'), 0)=1 AND "
        "COALESCE(HAS_PERMS_BY_NAME(N'ostv.' + QUOTENAME(t.[name]), "
        "N'OBJECT', N'DELETE'), 0)=1) THEN 1 ELSE 0 END), 0), "
        f"COALESCE(SUM(CASE WHEN t.[name] IN ({protected_placeholders}) AND ("
        "COALESCE(HAS_PERMS_BY_NAME(N'ostv.' + QUOTENAME(t.[name]), "
        "N'OBJECT', N'INSERT'), 0)=1 OR "
        "COALESCE(HAS_PERMS_BY_NAME(N'ostv.' + QUOTENAME(t.[name]), "
        "N'OBJECT', N'UPDATE'), 0)=1 OR "
        "COALESCE(HAS_PERMS_BY_NAME(N'ostv.' + QUOTENAME(t.[name]), "
        "N'OBJECT', N'DELETE'), 0)=1) THEN 1 ELSE 0 END), 0) "
        "FROM sys.tables t JOIN sys.schemas s ON s.[schema_id]=t.[schema_id] "
        "WHERE s.[name]=N'ostv' "
        f"AND t.[name] IN ({writable_placeholders}, {protected_placeholders})",
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
        f"COALESCE(HAS_PERMS_BY_NAME({marker_name}, N'OBJECT', N'SELECT'), 0), "
        f"COALESCE(HAS_PERMS_BY_NAME({marker_name}, N'OBJECT', N'INSERT'), 0), "
        f"COALESCE(HAS_PERMS_BY_NAME({marker_name}, N'OBJECT', N'UPDATE'), 0), "
        f"COALESCE(HAS_PERMS_BY_NAME({marker_name}, N'OBJECT', N'DELETE'), 0), "
        f"COALESCE(HAS_PERMS_BY_NAME({marker_name}, N'OBJECT', "
        "N'VIEW CHANGE TRACKING'), 0)",
        *(SQL_CLIENT_TRANSACTION_MARKER_TABLE for _ in range(5)),
    )
    marker_row = cursor.fetchone()
    if not _sql_integer_values_match(
        collaboration_row,
        (len(SQL_CLIENT_COLLABORATION_WRITE_TABLES), 0, 0),
    ) or not _sql_integer_values_match(marker_row, (1, 1, 0, 0, 1)):
        raise SqlInfrastructureError(
            SqlErrorDetails(
                SqlErrorCode.PERMISSION_DENIED,
                "SQL editing requires the canonical collaboration permissions.",
            )
        )


def apply_sql_client_permissions(cursor, database_user: str = "") -> None:
    permission_statements = [
        "SET @statement=N'ALTER USER ' + QUOTENAME(@database_user) + "
        "N' WITH DEFAULT_SCHEMA=[dbo]'; EXEC sys.sp_executesql @statement;",
        *(
            f"IF IS_ROLEMEMBER(N'{role}', @database_user) <> 1 "
            f"BEGIN SET @statement=N'ALTER ROLE [{role}] ADD MEMBER ' + "
            "QUOTENAME(@database_user); EXEC sys.sp_executesql @statement; END;"
            for role in SQL_CLIENT_DATABASE_ROLES
        ),
        *(
            f"SET @statement=N'GRANT VIEW DEFINITION ON SCHEMA::[{schema}] TO ' + "
            "QUOTENAME(@database_user); EXEC sys.sp_executesql @statement;"
            for schema in SQL_CLIENT_SCHEMA_VISIBILITY
        ),
        *(
            "SET @statement=N'DENY INSERT, UPDATE, DELETE ON "
            f"[ostv].[{table}] TO ' + QUOTENAME(@database_user); "
            "EXEC sys.sp_executesql @statement;"
            for table in SQL_CLIENT_PROTECTED_OSTV_TABLES
        ),
        "SET @statement=N'DENY UPDATE, DELETE ON "
        f"[ostv].[{SQL_CLIENT_TRANSACTION_MARKER_TABLE}] TO ' + "
        "QUOTENAME(@database_user); EXEC sys.sp_executesql @statement;",
        "SET @statement=N'GRANT VIEW CHANGE TRACKING ON OBJECT::"
        f"[ostv].[{SQL_CLIENT_TRANSACTION_MARKER_TABLE}] TO ' + "
        "QUOTENAME(@database_user); EXEC sys.sp_executesql @statement;",
    ]
    cursor.execute(
        "DECLARE @database_user sysname=NULLIF(LTRIM(RTRIM(?)), N''); "
        "IF @database_user IS NULL SET @database_user=USER_NAME(); "
        "IF @database_user=N'dbo' RETURN; "
        "IF DATABASE_PRINCIPAL_ID(@database_user) IS NULL AND "
        "USER_NAME()=N'dbo' AND SUSER_SID(@database_user)=SUSER_SID(ORIGINAL_LOGIN()) "
        "RETURN; "
        "IF @database_user IN (N'guest', N'INFORMATION_SCHEMA', N'sys') "
        "THROW 51000, 'A dedicated SQL database user is required.', 1; "
        "IF DATABASE_PRINCIPAL_ID(@database_user) IS NULL "
        "THROW 51000, 'The configured SQL database user does not exist.', 1; "
        "DECLARE @statement nvarchar(max); " + " ".join(permission_statements),
        database_user,
    )
