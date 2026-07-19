from __future__ import annotations

import argparse
import json
import os
import secrets
import uuid
import winreg
from pathlib import Path

import pyodbc

from ost_visualizer.domain.entities.database_descriptor import (
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.sql.connection_manager import (
    SqlConnectionManager,
    SqlConnectionRequest,
)
from ost_visualizer.infrastructure.sql.credential_store import WindowsCredentialStore
from tools.manage_sql_development import require_owned_sql_instance

_SERVER = "tcp:localhost"
_LOGIN = "OSTV_IT_EXECUTOR"
_CREDENTIAL_TARGET = "OSTVisualizer/Integration/OSTVDEV/Executor"
_SERVER_MARKER_PROPERTY = "OSTVisualizerDisposableTestServer"
_BACKUP_ROOT_PROPERTY = "OSTVisualizerDisposableBackupRoot"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Provision the guarded local OST Visualizer SQL test executor."
    )
    parser.add_argument("--backup-root", required=True)
    args = parser.parse_args()

    backup_root = _validated_backup_root(args.backup_root)
    credential_store = WindowsCredentialStore()
    existing_password = credential_store.read_password(_CREDENTIAL_TARGET) or ""
    reuse_credential = bool(existing_password) and _executor_login_accepts(
        existing_password
    )
    password = existing_password if reuse_credential else secrets.token_urlsafe(48)
    master_key_password = secrets.token_urlsafe(48)
    connection = pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={{{_SERVER}}};DATABASE={{master}};Trusted_Connection=yes;"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=10;"
        "MARS_Connection=no;APP=OST Visualizer SQL Integration Provisioner;",
        autocommit=True,
        timeout=10,
    )
    try:
        require_owned_sql_instance(connection)
        marker = _server_marker(connection)
        _configure_server(
            connection,
            marker,
            backup_root,
            password,
            master_key_password,
            update_executor_password=not reuse_credential,
        )
        if not reuse_credential:
            credential_store.write_password(_CREDENTIAL_TARGET, _LOGIN, password)
        _set_user_environment(marker)
        version, edition = _server_identity(connection)
    finally:
        connection.close()
        existing_password = ""
        password = ""
        master_key_password = ""

    print(
        json.dumps(
            {
                "status": "configured",
                "instance": "OSTVDEV",
                "port": 1433,
                "version": version,
                "edition": edition,
                "credential_target_configured": True,
                "credential_rotated": not reuse_credential,
                "server_marker_configured": True,
            },
            sort_keys=True,
        )
    )
    return 0


def _server_marker(connection) -> str:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT CONVERT(nvarchar(128), value) FROM sys.extended_properties "
            "WHERE class=0 AND name=?",
            _SERVER_MARKER_PROPERTY,
        )
        row = cursor.fetchone()
        return str(row[0]) if row is not None else str(uuid.uuid4())
    finally:
        cursor.close()


def _configure_server(
    connection,
    marker: str,
    backup_root: str,
    executor_password: str,
    master_key_password: str,
    *,
    update_executor_password: bool,
) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "EXEC sys.sp_configure N'show advanced options', 1; RECONFIGURE; "
            "EXEC sys.sp_configure N'contained database authentication', 0; "
            "RECONFIGURE;"
        )
        _set_extended_property(cursor, _SERVER_MARKER_PROPERTY, marker)
        _set_extended_property(cursor, _BACKUP_ROOT_PROPERTY, backup_root)
        if update_executor_password:
            cursor.execute(
                "DECLARE @secret nvarchar(128)=?; "
                "DECLARE @statement nvarchar(max); "
                f"IF SUSER_ID(N'{_LOGIN}') IS NULL "
                "SET @statement=N'CREATE LOGIN "
                f"[{_LOGIN}] WITH PASSWORD=' + QUOTENAME(@secret, NCHAR(39)) + "
                "N', CHECK_POLICY=ON, CHECK_EXPIRATION=OFF, "
                "DEFAULT_DATABASE=[master]'; "
                "ELSE SET @statement=N'ALTER LOGIN "
                f"[{_LOGIN}] WITH PASSWORD=' + QUOTENAME(@secret, NCHAR(39)); "
                "EXEC sys.sp_executesql @statement; "
                f"ALTER LOGIN [{_LOGIN}] ENABLE;",
                executor_password,
            )
        cursor.execute(
            "IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name=N'ostv_it') "
            "EXEC(N'CREATE SCHEMA [ostv_it] AUTHORIZATION [dbo]');"
        )
        cursor.execute(
            "IF OBJECT_ID(N'ostv_it.PendingRestores', N'U') IS NULL "
            "CREATE TABLE [ostv_it].[PendingRestores] ("
            "[DatabaseName] sysname NOT NULL PRIMARY KEY, "
            "[RunMarker] nvarchar(128) NOT NULL, "
            "[RequestedAtUtc] datetime2(7) NOT NULL "
            "CONSTRAINT [DF_PendingRestores_RequestedAtUtc] "
            "DEFAULT SYSUTCDATETIME())"
        )
        cursor.execute(_create_database_procedure())
        cursor.execute(_drop_database_procedure())
        cursor.execute(_restore_database_procedure())
        cursor.execute(_validate_restored_database_procedure())
        cursor.execute(
            "DECLARE @secret nvarchar(128)=?; "
            "IF NOT EXISTS (SELECT 1 FROM sys.symmetric_keys WHERE "
            "name=N'##MS_DatabaseMasterKey##') BEGIN "
            "DECLARE @statement nvarchar(max)=N'CREATE MASTER KEY ENCRYPTION "
            "BY PASSWORD=' + QUOTENAME(@secret, NCHAR(39)); "
            "EXEC sys.sp_executesql @statement; END",
            master_key_password,
        )
        cursor.execute(
            "IF NOT EXISTS (SELECT 1 FROM sys.certificates WHERE "
            "name=N'OSTV_IT_ProvisioningCertificate') "
            "CREATE CERTIFICATE [OSTV_IT_ProvisioningCertificate] "
            "WITH SUBJECT=N'OST Visualizer disposable SQL database provisioning'; "
            "IF SUSER_ID(N'OSTV_IT_ProvisioningCertificateLogin') IS NULL "
            "CREATE LOGIN [OSTV_IT_ProvisioningCertificateLogin] FROM CERTIFICATE "
            "[OSTV_IT_ProvisioningCertificate]; "
            "GRANT CREATE ANY DATABASE TO "
            "[OSTV_IT_ProvisioningCertificateLogin]; "
            "GRANT ALTER ANY DATABASE TO "
            "[OSTV_IT_ProvisioningCertificateLogin]; "
            "GRANT CONNECT ANY DATABASE TO "
            "[OSTV_IT_ProvisioningCertificateLogin];"
        )
        for procedure in (
            "CreateDatabase",
            "DropDatabase",
            "RestoreDatabase",
            "ValidateRestoredDatabase",
        ):
            cursor.execute(
                "ADD SIGNATURE TO OBJECT::[ostv_it].[" + procedure + "] "
                "BY CERTIFICATE [OSTV_IT_ProvisioningCertificate]"
            )
        cursor.execute(
            f"IF USER_ID(N'{_LOGIN}') IS NULL CREATE USER [{_LOGIN}] "
            f"FOR LOGIN [{_LOGIN}]; "
            f"REVOKE EXECUTE ON SCHEMA::[ostv_it] FROM [{_LOGIN}]; "
            f"GRANT EXECUTE ON OBJECT::[ostv_it].[CreateDatabase] TO [{_LOGIN}]; "
            f"GRANT EXECUTE ON OBJECT::[ostv_it].[DropDatabase] TO [{_LOGIN}]; "
            f"GRANT EXECUTE ON OBJECT::[ostv_it].[RestoreDatabase] TO [{_LOGIN}]; "
            f"GRANT EXECUTE ON OBJECT::[ostv_it].[ValidateRestoredDatabase] "
            f"TO [{_LOGIN}];"
        )
    finally:
        cursor.close()


def _set_extended_property(cursor, name: str, value: str) -> None:
    cursor.execute(
        "IF EXISTS (SELECT 1 FROM sys.extended_properties WHERE class=0 "
        "AND name=?) EXEC sys.sp_updateextendedproperty @name=?, @value=? "
        "ELSE EXEC sys.sp_addextendedproperty @name=?, @value=?",
        name,
        name,
        value,
        name,
        value,
    )


def _create_database_procedure() -> str:
    return r"""
CREATE OR ALTER PROCEDURE [ostv_it].[CreateDatabase]
    @DatabaseName sysname,
    @RunMarker nvarchar(128),
    @ExpectedServerMarker nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @ServerMarker nvarchar(128) = (
        SELECT CONVERT(nvarchar(128), value)
        FROM sys.extended_properties
        WHERE class=0 AND name=N'OSTVisualizerDisposableTestServer'
    );
    IF @ServerMarker IS NULL OR @ExpectedServerMarker IS NULL
       OR @ServerMarker COLLATE Latin1_General_100_BIN2
          <> @ExpectedServerMarker COLLATE Latin1_General_100_BIN2
        THROW 51000, 'Disposable SQL server marker does not match.', 1;
    IF @RunMarker IS NULL OR LEN(@RunMarker)=0 OR LEN(@RunMarker)>128
        THROW 51003, 'Disposable database marker is invalid.', 1;
    IF @DatabaseName COLLATE Latin1_General_100_BIN2 NOT LIKE N'OSTV_IT[_]%'
       OR LEN(@DatabaseName) <= LEN(N'OSTV_IT_')
       OR @DatabaseName COLLATE Latin1_General_100_BIN2 LIKE N'%[^A-Za-z0-9_]%'
        THROW 51001, 'Database name is outside the disposable test scope.', 1;
    IF DB_ID(@DatabaseName) IS NOT NULL
        THROW 51002, 'Disposable test database already exists.', 1;
    DECLARE @Sql nvarchar(max) = N'CREATE DATABASE ' + QUOTENAME(@DatabaseName);
    EXEC (@Sql);
    SET @Sql = N'ALTER DATABASE ' + QUOTENAME(@DatabaseName)
        + N' SET CHANGE_TRACKING = ON '
        + N'(CHANGE_RETENTION = 7 DAYS, AUTO_CLEANUP = ON)';
    EXEC (@Sql);
    SET @Sql = N'EXEC ' + QUOTENAME(@DatabaseName)
        + N'.sys.sp_addextendedproperty @name=N''OSTVisualizerDisposableTestRun'', '
        + N'@value=@Marker';
    EXEC sys.sp_executesql @Sql, N'@Marker nvarchar(128)', @Marker=@RunMarker;
END
"""


def _drop_database_procedure() -> str:
    return r"""
CREATE OR ALTER PROCEDURE [ostv_it].[DropDatabase]
    @DatabaseName sysname,
    @RunMarker nvarchar(128),
    @ExpectedServerMarker nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @ServerMarker nvarchar(128) = (
        SELECT CONVERT(nvarchar(128), value) FROM sys.extended_properties
        WHERE class=0 AND name=N'OSTVisualizerDisposableTestServer'
    );
    IF @ServerMarker IS NULL OR @ExpectedServerMarker IS NULL
       OR @ServerMarker COLLATE Latin1_General_100_BIN2
          <> @ExpectedServerMarker COLLATE Latin1_General_100_BIN2
        THROW 51010, 'Disposable SQL server marker does not match.', 1;
    IF @RunMarker IS NULL OR LEN(@RunMarker)=0 OR LEN(@RunMarker)>128
        THROW 51013, 'Disposable database marker is invalid.', 1;
    IF @DatabaseName COLLATE Latin1_General_100_BIN2 NOT LIKE N'OSTV_IT[_]%'
       OR LEN(@DatabaseName) <= LEN(N'OSTV_IT_')
       OR @DatabaseName COLLATE Latin1_General_100_BIN2 LIKE N'%[^A-Za-z0-9_]%'
        THROW 51011, 'Database name is outside the disposable test scope.', 1;
    IF DB_ID(@DatabaseName) IS NULL RETURN;
    DECLARE @ActualMarker nvarchar(128);
    DECLARE @Sql nvarchar(max) = N'USE ' + QUOTENAME(@DatabaseName)
        + N'; SELECT @Value=CONVERT(nvarchar(128), value) FROM '
        + N'sys.extended_properties WHERE class=0 '
        + N'AND name=N''OSTVisualizerDisposableTestRun''';
    EXEC sys.sp_executesql @Sql,
        N'@Value nvarchar(128) OUTPUT', @Value=@ActualMarker OUTPUT;
    IF @ActualMarker IS NULL OR @ActualMarker COLLATE Latin1_General_100_BIN2
       <> @RunMarker COLLATE Latin1_General_100_BIN2
        THROW 51012, 'Disposable test database marker does not match.', 1;
    SET @Sql = N'ALTER DATABASE ' + QUOTENAME(@DatabaseName)
        + N' SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE '
        + QUOTENAME(@DatabaseName) + N';';
    EXEC (@Sql);
    DELETE FROM [ostv_it].[PendingRestores]
    WHERE [DatabaseName]=@DatabaseName
      AND [RunMarker] COLLATE Latin1_General_100_BIN2
          = @RunMarker COLLATE Latin1_General_100_BIN2;
END
"""


def _restore_database_procedure() -> str:
    return r"""
CREATE OR ALTER PROCEDURE [ostv_it].[RestoreDatabase]
    @DatabaseName sysname,
    @RunMarker nvarchar(128),
    @BackupPath nvarchar(4000),
    @ExpectedServerMarker nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @ServerMarker nvarchar(128) = (
        SELECT CONVERT(nvarchar(128), value) FROM sys.extended_properties
        WHERE class=0 AND name=N'OSTVisualizerDisposableTestServer'
    );
    IF @ServerMarker IS NULL OR @ExpectedServerMarker IS NULL
       OR @ServerMarker COLLATE Latin1_General_100_BIN2
          <> @ExpectedServerMarker COLLATE Latin1_General_100_BIN2
        THROW 51019, 'Disposable SQL server marker does not match.', 1;
    IF @RunMarker IS NULL OR LEN(@RunMarker)=0 OR LEN(@RunMarker)>128
        THROW 51023, 'Disposable database marker is invalid.', 1;
    DECLARE @BackupRoot nvarchar(4000) = (
        SELECT CONVERT(nvarchar(4000), value)
        FROM sys.extended_properties
        WHERE class=0 AND name=N'OSTVisualizerDisposableBackupRoot'
    );
    IF RIGHT(@BackupRoot, 1) NOT IN (N'\', N'/') SET @BackupRoot += N'\';
    IF @BackupRoot IS NULL
       OR LEFT(@BackupPath, LEN(@BackupRoot)) <> @BackupRoot
       OR @BackupPath LIKE N'%..%'
        THROW 51020, 'Backup path is outside the disposable test scope.', 1;
    IF @DatabaseName COLLATE Latin1_General_100_BIN2 NOT LIKE N'OSTV_IT[_]%'
       OR LEN(@DatabaseName) <= LEN(N'OSTV_IT_')
       OR @DatabaseName COLLATE Latin1_General_100_BIN2 LIKE N'%[^A-Za-z0-9_]%'
        THROW 51021, 'Database name is outside the disposable test scope.', 1;
    IF DB_ID(@DatabaseName) IS NOT NULL
        THROW 51022, 'Restore target already exists.', 1;
    IF EXISTS (
        SELECT 1 FROM [ostv_it].[PendingRestores]
        WHERE [DatabaseName]=@DatabaseName
    )
        THROW 51024, 'Restore target already has pending validation.', 1;
    DECLARE @Sql nvarchar(max) = N'RESTORE VERIFYONLY FROM DISK='
        + QUOTENAME(@BackupPath, '''') + N' WITH CHECKSUM';
    EXEC (@Sql);
    INSERT INTO [ostv_it].[PendingRestores] ([DatabaseName], [RunMarker])
    VALUES (@DatabaseName, @RunMarker);
END
"""


def _validate_restored_database_procedure() -> str:
    return r"""
CREATE OR ALTER PROCEDURE [ostv_it].[ValidateRestoredDatabase]
    @DatabaseName sysname,
    @RunMarker nvarchar(128),
    @ExpectedServerMarker nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @ServerMarker nvarchar(128) = (
        SELECT CONVERT(nvarchar(128), value) FROM sys.extended_properties
        WHERE class=0 AND name=N'OSTVisualizerDisposableTestServer'
    );
    IF @ServerMarker IS NULL OR @ExpectedServerMarker IS NULL
       OR @ServerMarker COLLATE Latin1_General_100_BIN2
          <> @ExpectedServerMarker COLLATE Latin1_General_100_BIN2
        THROW 51030, 'Disposable SQL server marker does not match.', 1;
    IF @RunMarker IS NULL OR LEN(@RunMarker)=0 OR LEN(@RunMarker)>128
        THROW 51033, 'Disposable database marker is invalid.', 1;
    IF @DatabaseName COLLATE Latin1_General_100_BIN2 NOT LIKE N'OSTV_IT[_]%'
       OR LEN(@DatabaseName) <= LEN(N'OSTV_IT_')
       OR @DatabaseName COLLATE Latin1_General_100_BIN2 LIKE N'%[^A-Za-z0-9_]%'
        THROW 51031, 'Database name is outside the disposable test scope.', 1;
    IF NOT EXISTS (
        SELECT 1 FROM [ostv_it].[PendingRestores]
        WHERE [DatabaseName]=@DatabaseName
          AND [RunMarker] COLLATE Latin1_General_100_BIN2
              = @RunMarker COLLATE Latin1_General_100_BIN2
    )
        THROW 51032, 'Restore validation request does not match.', 1;
    DECLARE @ActualMarker nvarchar(128);
    DECLARE @Sql nvarchar(max) = N'USE ' + QUOTENAME(@DatabaseName)
        + N'; SELECT @Value=CONVERT(nvarchar(128), value) FROM '
        + N'sys.extended_properties WHERE class=0 '
        + N'AND name=N''OSTVisualizerDisposableTestRun''';
    EXEC sys.sp_executesql @Sql,
        N'@Value nvarchar(128) OUTPUT', @Value=@ActualMarker OUTPUT;
    IF @ActualMarker IS NULL OR @ActualMarker COLLATE Latin1_General_100_BIN2
       <> @RunMarker COLLATE Latin1_General_100_BIN2
        THROW 51034, 'Restored database marker does not match.', 1;
    SET @Sql = N'ALTER DATABASE ' + QUOTENAME(@DatabaseName)
        + N' SET MULTI_USER';
    EXEC (@Sql);
    DELETE FROM [ostv_it].[PendingRestores]
    WHERE [DatabaseName]=@DatabaseName
      AND [RunMarker] COLLATE Latin1_General_100_BIN2
          = @RunMarker COLLATE Latin1_General_100_BIN2;
END
"""


def _set_user_environment(marker: str) -> None:
    values = {
        "OSTV_SQL_TEST_SERVER": _SERVER,
        "OSTV_SQL_TEST_AUTH": "sql",
        "OSTV_SQL_TEST_USER": _LOGIN,
        "OSTV_SQL_TEST_SERVER_MARKER": marker,
        "OSTV_SQL_TEST_CREDENTIAL_TARGET": _CREDENTIAL_TARGET,
    }
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        "Environment",
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        for name in (
            "OSTV_SQL_INTEGRATION",
            "OSTV_SQL_DESTRUCTIVE_TESTS",
            "OSTV_SQL_TEST_PASSWORD",
        ):
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass


def _validated_backup_root(value: str) -> str:
    configured = Path(value).resolve()
    expected = (
        Path(os.environ.get("ProgramData", r"C:\ProgramData"))
        / "OSTVisualizer"
        / "SqlIntegrationBackups"
    ).resolve()
    if os.path.normcase(configured) != os.path.normcase(expected):
        raise ValueError("The SQL integration backup root must use the dedicated path.")
    configured.mkdir(parents=True, exist_ok=True)
    return str(configured)


def _executor_login_accepts(password: str) -> bool:
    location = SqlServerDatabaseLocation(
        server=_SERVER,
        database="master",
        authentication_mode=SqlAuthenticationMode.SQL_SERVER,
        username=_LOGIN,
        encrypt=True,
        trust_server_certificate=False,
        connection_timeout_seconds=5,
    )
    try:
        with SqlConnectionManager().connection(
            SqlConnectionRequest(location, password=password, read_only=True),
            autocommit=True,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return int(cursor.fetchone()[0]) == 1
    except (OSError, RuntimeError, ValueError):
        return False


def _server_identity(connection) -> tuple[str, str]:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT CONVERT(nvarchar(128), SERVERPROPERTY('ProductVersion')), "
            "CONVERT(nvarchar(128), SERVERPROPERTY('Edition'))"
        )
        row = cursor.fetchone()
        return str(row[0]), str(row[1])
    finally:
        cursor.close()


if __name__ == "__main__":
    raise SystemExit(main())
