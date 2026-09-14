from __future__ import annotations
from dataclasses import dataclass
from .client_permissions import (
    apply_sql_client_permissions,
    require_sql_client_editability,
)
from .connection_manager import SqlConnectionManager, SqlConnectionRequest
from .database_metadata_contract import DATABASE_METADATA_CURRENT_DATABASE_PREDICATE
from .errors import SqlErrorCode, SqlErrorDetails, SqlInfrastructureError
from .schema_lock import acquire_schema_transaction_lock


@dataclass(frozen=True)
class SqlAuthenticatedClient:
    login_name: str
    sid: bytes
    server_name: str


def authenticate_runtime_client(
    connections: SqlConnectionManager, request: SqlConnectionRequest
) -> SqlAuthenticatedClient:
    with connections.connection(request, autocommit=True) as lease:
        with lease.cursor() as cursor:
            cursor.execute(
                "SELECT ORIGINAL_LOGIN(), SUSER_SID(), "
                "CONVERT(nvarchar(128), SERVERPROPERTY(N'ServerName')), "
                "(SELECT [type] FROM sys.server_principals "
                "WHERE [sid]=SUSER_SID() AND [name]=ORIGINAL_LOGIN())"
            )
            row = cursor.fetchone()
            if (
                row is None
                or not row[0]
                or not row[1]
                or not row[2]
                or row[3] not in {"S", "U"}
            ):
                raise _permission_error(
                    "Normal database access requires an existing individual SQL "
                    "or Windows login. Ask your SQL administrator to provision "
                    "that login first. Group-only Windows access is not supported "
                    "by this creation workflow."
                )
            _require_restricted_server_access(cursor)
            return SqlAuthenticatedClient(str(row[0]), bytes(row[1]), str(row[2]))


def provision_runtime_client(
    connections: SqlConnectionManager,
    creator_request: SqlConnectionRequest,
    client: SqlAuthenticatedClient,
) -> None:
    with connections.connection(creator_request, autocommit=False) as lease:
        committed = False
        try:
            with lease.cursor() as cursor:
                acquire_schema_transaction_lock(cursor)
                _require_database_identity(
                    cursor, creator_request.location.database_guid
                )
                cursor.execute(
                    "SET NOCOUNT ON; DECLARE @login sysname=?; "
                    "IF DATABASE_PRINCIPAL_ID(@login) IS NOT NULL "
                    "THROW 51000, 'The runtime database user already exists.', 1; "
                    "DECLARE @statement nvarchar(max)=N'CREATE USER ' + "
                    "QUOTENAME(@login) + N' FOR LOGIN ' + QUOTENAME(@login) + "
                    "N' WITH DEFAULT_SCHEMA=[dbo]'; EXEC sys.sp_executesql @statement; "
                    "SELECT [sid] FROM sys.database_principals WHERE [name]=@login",
                    client.login_name,
                )
                row = cursor.fetchone()
                if row is None or bytes(row[0] or b"") != client.sid:
                    raise _permission_error(
                        "The normal-use login changed during creation. "
                        "Ask your SQL administrator to check its user mapping."
                    )
                apply_sql_client_permissions(cursor, client.login_name)
            lease.commit()
            committed = True
        finally:
            if not committed:
                lease.rollback()


def verify_runtime_client(
    connections: SqlConnectionManager,
    request: SqlConnectionRequest,
    client: SqlAuthenticatedClient,
) -> None:
    with connections.connection(request, autocommit=True) as lease:
        with lease.cursor() as cursor:
            _require_database_identity(cursor, request.location.database_guid)
            cursor.execute(
                "SELECT SUSER_SID(), USER_NAME(), "
                "COALESCE(IS_ROLEMEMBER(N'db_owner'), 0), "
                "(SELECT COUNT(*) FROM sys.fn_my_permissions(NULL, N'DATABASE') "
                "WHERE permission_name IN (N'CONTROL', N'ALTER', N'CREATE TABLE', "
                "N'CREATE SCHEMA', N'ALTER ANY USER', N'ALTER ANY ROLE'))"
            )
            row = cursor.fetchone()
            if (
                row is None
                or bytes(row[0] or b"") != client.sid
                or row[1] != client.login_name
                or row[1] == "dbo"
                or row[2] != 0
                or row[3] != 0
            ):
                raise _permission_error(
                    "The normal-use connection must use the provisioned "
                    "restricted user, without database ownership or DDL rights."
                )
            _require_restricted_server_access(cursor)
            require_sql_client_editability(cursor)


def _require_database_identity(cursor, database_guid: str) -> None:
    cursor.execute(
        "SELECT m.[DatabaseGuid] FROM [ostv].[DatabaseMetadata] m WHERE "
        + DATABASE_METADATA_CURRENT_DATABASE_PREDICATE
        + " AND m.[DatabaseGuid]=CONVERT(uniqueidentifier, ?)",
        database_guid,
    )
    if cursor.fetchone() is None:
        raise _permission_error(
            "The newly initialized database was replaced or its identity changed. "
            "No runtime connection will be saved."
        )


def _require_restricted_server_access(cursor) -> None:
    cursor.execute(
        "SELECT (SELECT COUNT(*) FROM sys.login_token "
        "WHERE [type]=N'SERVER ROLE' AND [name]<>N'public'), "
        "(SELECT COUNT(*) FROM sys.fn_my_permissions(NULL, N'SERVER') "
        "WHERE permission_name IN (N'CONTROL SERVER', N'CREATE ANY DATABASE', "
        "N'ALTER ANY DATABASE', N'ALTER ANY LOGIN', N'ALTER ANY SERVER ROLE', "
        "N'IMPERSONATE ANY LOGIN')), "
        "COALESCE(HAS_PERMS_BY_NAME(N'master', N'DATABASE', N'CREATE DATABASE'), 0)"
    )
    row = cursor.fetchone()
    if row is None or tuple(row) != (0, 0, 0):
        raise _permission_error(
            "Choose a separate normal-use login without server roles, "
            "database-creation rights, or server administration permissions. "
            "The creator's privileges will not be changed."
        )


def _permission_error(message: str) -> SqlInfrastructureError:
    return SqlInfrastructureError(
        SqlErrorDetails(SqlErrorCode.PERMISSION_DENIED, message)
    )
