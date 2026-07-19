from __future__ import annotations
from .schema_definition import LATEST_SQL_SCHEMA

SQL_CLIENT_DATABASE_ROLES = ("db_datareader", "db_datawriter")
SQL_CLIENT_SCHEMA_VISIBILITY = ("dbo", "ostv")
SQL_CLIENT_COLLABORATION_WRITE_TABLES = (
    "Sessions",
    "Presence",
    "Locks",
    "EntityVersions",
    "ChangeLog",
    "ChangeFeedState",
)
SQL_CLIENT_PROTECTED_OSTV_TABLES = tuple(
    table.name
    for table in LATEST_SQL_SCHEMA.tables
    if table.name not in SQL_CLIENT_COLLABORATION_WRITE_TABLES
)


def apply_sql_client_permissions(cursor, database_user: str = "") -> None:
    permission_statements = [
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
