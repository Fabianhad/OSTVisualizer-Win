import os
import secrets
import unittest
from dataclasses import replace
import pyodbc
from ost_visualizer.domain.entities.database_descriptor import SqlAuthenticationMode
from ost_visualizer.infrastructure.sql.connection_manager import (
    SqlConnectionManager,
    SqlConnectionRequest,
)
from ost_visualizer.infrastructure.sql.client_permissions import (
    apply_sql_client_permissions,
)
from ost_visualizer.infrastructure.sql.errors import SqlInfrastructureError
from tests.sql_integration_support import (
    DisposableSqlConfiguration,
    DisposableSqlDatabase,
    _require_test_database_name,
)


def _execute_batch(
    manager: SqlConnectionManager,
    request: SqlConnectionRequest,
    statement: str,
    *parameters: object,
) -> None:
    connection = pyodbc.connect(
        manager.build_connection_string(request),
        autocommit=True,
    )
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(statement, *parameters)
            while cursor.nextset():
                pass
        finally:
            cursor.close()
    finally:
        connection.close()


class SqlDevelopmentEnvironmentIntegrationTests(unittest.TestCase):
    def test_authentication_encryption_and_engine_capabilities(self):
        configuration = DisposableSqlConfiguration.from_environment()
        manager = SqlConnectionManager()
        windows_location = replace(
            configuration.location,
            authentication_mode=SqlAuthenticationMode.WINDOWS,
            username="",
        )
        with manager.connection(
            SqlConnectionRequest(windows_location, database_override="master"),
            autocommit=True,
        ) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    "SELECT CONVERT(nvarchar(128), SERVERPROPERTY('Edition')), "
                    "CONVERT(nvarchar(128), SERVERPROPERTY('ProductVersion')), "
                    "encrypt_option, net_transport FROM sys.dm_exec_connections "
                    "WHERE session_id=@@SPID"
                )
                windows_row = cursor.fetchone()
        self.assertIn("Developer", str(windows_row[0]))
        self.assertGreaterEqual(
            tuple(map(int, str(windows_row[1]).split("."))), (16, 0, 4262, 2)
        )
        self.assertEqual(str(windows_row[2]), "TRUE")
        self.assertEqual(str(windows_row[3]), "TCP")
        with manager.connection(
            SqlConnectionRequest(
                configuration.location,
                password=configuration.password,
                database_override="master",
            ),
            autocommit=True,
        ) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    "SELECT IS_SRVROLEMEMBER(N'sysadmin'), "
                    "IS_SRVROLEMEMBER(N'dbcreator'), "
                    "COALESCE(HAS_PERMS_BY_NAME(NULL, NULL, "
                    "N'CREATE ANY DATABASE'), 0)"
                )
                permission_row = cursor.fetchone()
        self.assertEqual(tuple(map(int, permission_row)), (0, 0, 0))

    def test_change_tracking_rowversion_transactions_and_application_locks(self):
        configuration = DisposableSqlConfiguration.from_environment()
        with DisposableSqlDatabase(configuration) as database:
            request = SqlConnectionRequest(
                database.location,
                password=configuration.password,
            )
            windows_master = replace(
                configuration.location,
                authentication_mode=SqlAuthenticationMode.WINDOWS,
                username="",
            )
            admin_request = SqlConnectionRequest(
                windows_master,
                database_override="master",
            )
            _execute_batch(
                database.connections,
                admin_request,
                f"ALTER DATABASE [{database.database_name}] "
                "SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
                "BEGIN TRY "
                f"ALTER DATABASE [{database.database_name}] SET "
                "CHANGE_TRACKING = ON (CHANGE_RETENTION = 2 DAYS, "
                "AUTO_CLEANUP = ON); "
                f"ALTER DATABASE [{database.database_name}] SET MULTI_USER; "
                "END TRY BEGIN CATCH "
                f"ALTER DATABASE [{database.database_name}] SET MULTI_USER; "
                "THROW; END CATCH",
            )
            with database.connections.connection(request, autocommit=True) as lease:
                with lease.cursor() as cursor:
                    cursor.execute(
                        "CREATE TABLE [ostv_it].[ChangeTrackingProbe] "
                        "([Id] int NOT NULL PRIMARY KEY, [Value] nvarchar(64) "
                        "NOT NULL, [Token] rowversion NOT NULL); "
                        "ALTER TABLE [ostv_it].[ChangeTrackingProbe] ENABLE "
                        "CHANGE_TRACKING"
                    )
            with database.connections.connection(request, autocommit=False) as lease:
                with lease.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO [ostv_it].[ChangeTrackingProbe] "
                        "([Id], [Value]) VALUES (1, N'committed')"
                    )
                lease.commit()
            with database.connections.connection(request, autocommit=True) as lease:
                with lease.cursor() as cursor:
                    cursor.execute(
                        "SELECT CHANGE_TRACKING_CURRENT_VERSION(), "
                        "CHANGE_TRACKING_MIN_VALID_VERSION("
                        "OBJECT_ID(N'ostv_it.ChangeTrackingProbe'))"
                    )
                    versions = cursor.fetchone()
                    cursor.execute(
                        "SELECT [SYS_CHANGE_OPERATION] FROM "
                        "CHANGETABLE(CHANGES [ostv_it].[ChangeTrackingProbe], 0) c "
                        "WHERE c.[Id]=1"
                    )
                    change = cursor.fetchone()
                    cursor.execute(
                        "SELECT [Token] FROM [ostv_it].[ChangeTrackingProbe] "
                        "WHERE [Id]=1"
                    )
                    original_token = bytes(cursor.fetchone()[0])
            self.assertGreater(int(versions[0]), 0)
            self.assertGreaterEqual(int(versions[1]), 0)
            self.assertEqual(str(change[0]), "I")
            with database.connections.connection(request, autocommit=False) as lease:
                with lease.cursor() as cursor:
                    cursor.execute(
                        "UPDATE [ostv_it].[ChangeTrackingProbe] SET "
                        "[Value]=N'rolled-back' WHERE [Id]=1"
                    )
                lease.rollback()
            with database.connections.connection(request, autocommit=True) as lease:
                with lease.cursor() as cursor:
                    cursor.execute(
                        "SELECT [Value], [Token] FROM "
                        "[ostv_it].[ChangeTrackingProbe] WHERE [Id]=1"
                    )
                    rolled_back = cursor.fetchone()
            self.assertEqual(str(rolled_back[0]), "committed")
            self.assertEqual(bytes(rolled_back[1]), original_token)
            resource = f"OSTV_IT_LOCK_{database.run_marker}"
            with database.connections.connection(request, autocommit=True) as first:
                with database.connections.connection(
                    request, autocommit=True
                ) as second:
                    with first.cursor() as first_cursor, second.cursor() as second_cursor:
                        first_cursor.execute(
                            "DECLARE @Result int; EXEC @Result=sys.sp_getapplock "
                            "@Resource=?, @LockMode=N'Exclusive', "
                            "@LockOwner=N'Session', @LockTimeout=0; SELECT @Result",
                            resource,
                        )
                        self.assertGreaterEqual(int(first_cursor.fetchone()[0]), 0)
                        second_cursor.execute(
                            "DECLARE @Result int; EXEC @Result=sys.sp_getapplock "
                            "@Resource=?, @LockMode=N'Exclusive', "
                            "@LockOwner=N'Session', @LockTimeout=0; SELECT @Result",
                            resource,
                        )
                        self.assertLess(int(second_cursor.fetchone()[0]), 0)
                        first_cursor.execute(
                            "EXEC sys.sp_releaseapplock @Resource=?, "
                            "@LockOwner=N'Session'",
                            resource,
                        )
                        second_cursor.execute(
                            "DECLARE @Result int; EXEC @Result=sys.sp_getapplock "
                            "@Resource=?, @LockMode=N'Exclusive', "
                            "@LockOwner=N'Session', @LockTimeout=0; SELECT @Result",
                            resource,
                        )
                        self.assertGreaterEqual(int(second_cursor.fetchone()[0]), 0)

    def test_executor_cannot_bypass_guarded_database_procedures(self):
        configuration = DisposableSqlConfiguration.from_environment()
        direct_name = f"OSTV_IT_DIRECT_DENIED_{secrets.token_hex(6)}"
        _require_test_database_name(direct_name)
        direct_marker = secrets.token_hex(16)
        manager = SqlConnectionManager()
        executor_master = SqlConnectionRequest(
            configuration.location,
            password=configuration.password,
            database_override="master",
        )
        created = False
        try:
            with self.assertRaises(SqlInfrastructureError):
                with manager.connection(executor_master, autocommit=True) as lease:
                    with lease.cursor() as cursor:
                        cursor.execute(f"CREATE DATABASE [{direct_name}]")
                        created = True
        finally:
            if created:
                windows_location = replace(
                    configuration.location,
                    authentication_mode=SqlAuthenticationMode.WINDOWS,
                    username="",
                )
                with manager.connection(
                    SqlConnectionRequest(
                        windows_location,
                        database_override="master",
                    ),
                    autocommit=True,
                ) as lease:
                    with lease.cursor() as cursor:
                        cursor.execute(
                            f"EXEC [{direct_name}].sys.sp_addextendedproperty "
                            "@name=N'OSTVisualizerDisposableTestRun', @value=?",
                            direct_marker,
                        )
                with manager.connection(executor_master, autocommit=True) as lease:
                    with lease.cursor() as cursor:
                        cursor.execute(
                            "EXEC [ostv_it].[DropDatabase] "
                            "@DatabaseName=?, @RunMarker=?, "
                            "@ExpectedServerMarker=?",
                            direct_name,
                            direct_marker,
                            configuration.server_marker,
                        )
        mismatched_marker_name = f"OSTV_IT_MARKER_DENIED_{secrets.token_hex(6)}"
        with self.assertRaises(SqlInfrastructureError):
            with manager.connection(executor_master, autocommit=True) as lease:
                with lease.cursor() as cursor:
                    cursor.execute(
                        "EXEC [ostv_it].[CreateDatabase] "
                        "@DatabaseName=?, @RunMarker=?, @ExpectedServerMarker=?",
                        mismatched_marker_name,
                        secrets.token_hex(16),
                        "deliberately-invalid-marker",
                    )
        with manager.connection(executor_master, autocommit=True) as lease:
            with lease.cursor() as cursor:
                cursor.execute("SELECT DB_ID(?)", mismatched_marker_name)
                self.assertIsNone(cursor.fetchone()[0])
        with DisposableSqlDatabase(configuration) as database:
            with self.assertRaises(SqlInfrastructureError):
                with manager.connection(executor_master, autocommit=True) as lease:
                    with lease.cursor() as cursor:
                        cursor.execute(f"DROP DATABASE [{database.database_name}]")

    def test_disposable_database_is_removed_after_test_failure(self):
        configuration = DisposableSqlConfiguration.from_environment()
        database = DisposableSqlDatabase(configuration)
        with self.assertRaisesRegex(RuntimeError, "deliberate test failure"):
            with database:
                raise RuntimeError("deliberate test failure")
        master_request = SqlConnectionRequest(
            configuration.location,
            password=configuration.password,
            database_override="master",
            read_only=True,
        )
        with database.connections.connection(
            master_request,
            autocommit=True,
        ) as lease:
            with lease.cursor() as cursor:
                cursor.execute("SELECT DB_ID(?)", database.database_name)
                self.assertIsNone(cursor.fetchone()[0])

    def test_guarded_restore_preserves_data_and_database_marker(self):
        configuration = DisposableSqlConfiguration.from_environment()
        backup_root = os.path.join(
            os.environ.get("ProgramData", r"C:\ProgramData"),
            "OSTVisualizer",
            "SqlIntegrationBackups",
        )
        restored_name = f"OSTV_IT_RESTORE_{secrets.token_hex(8)}"
        _require_test_database_name(restored_name)
        database = DisposableSqlDatabase(configuration)
        backup_path = ""
        restored_marker_verified = False
        try:
            with database:
                backup_path = os.path.join(
                    backup_root,
                    f"{database.database_name}_{database.run_marker}.bak",
                )
                windows_location = replace(
                    database.location,
                    authentication_mode=SqlAuthenticationMode.WINDOWS,
                    username="",
                )
                with database.connections.connection(
                    SqlConnectionRequest(windows_location),
                    autocommit=True,
                ) as lease:
                    with lease.cursor() as cursor:
                        cursor.execute(
                            "CREATE TABLE [ostv_it].[RestoreProbe] "
                            "([Id] int NOT NULL PRIMARY KEY, "
                            "[Value] nvarchar(32) NOT NULL); "
                            "INSERT INTO [ostv_it].[RestoreProbe] "
                            "([Id], [Value]) VALUES (1, N'preserved')"
                        )
                escaped_path = backup_path.replace("'", "''")
                _execute_batch(
                    database.connections,
                    SqlConnectionRequest(windows_location),
                    f"BACKUP DATABASE [{database.database_name}] TO DISK="
                    f"N'{escaped_path}' WITH FORMAT, INIT, CHECKSUM",
                )
                self.assertTrue(os.path.isfile(backup_path))
                database.drop()
                master_request = SqlConnectionRequest(
                    configuration.location,
                    password=configuration.password,
                    database_override="master",
                )
                _execute_batch(
                    database.connections,
                    master_request,
                    "EXEC [ostv_it].[RestoreDatabase] "
                    "@DatabaseName=?, @RunMarker=?, @BackupPath=?, "
                    "@ExpectedServerMarker=?",
                    restored_name,
                    database.run_marker,
                    backup_path,
                    configuration.server_marker,
                )
                admin_master = replace(windows_location, database="master")
                escaped_path = backup_path.replace("'", "''")
                _execute_batch(
                    database.connections,
                    SqlConnectionRequest(admin_master),
                    f"RESTORE DATABASE [{restored_name}] FROM DISK="
                    f"N'{escaped_path}' WITH RECOVERY, RESTRICTED_USER",
                )
                _execute_batch(
                    database.connections,
                    master_request,
                    "EXEC [ostv_it].[ValidateRestoredDatabase] "
                    "@DatabaseName=?, @RunMarker=?, @ExpectedServerMarker=?",
                    restored_name,
                    database.run_marker,
                    configuration.server_marker,
                )
                restored_location = replace(
                    configuration.location,
                    database=restored_name,
                )
                with database.connections.connection(
                    SqlConnectionRequest(
                        restored_location,
                        password=configuration.password,
                    ),
                    autocommit=True,
                ) as lease:
                    with lease.cursor() as cursor:
                        cursor.execute(
                            "SELECT CONVERT(nvarchar(128), value) FROM "
                            "sys.extended_properties WHERE class=0 AND "
                            "name=N'OSTVisualizerDisposableTestRun'"
                        )
                        restored_marker = str(cursor.fetchone()[0])
                        restored_marker_verified = secrets.compare_digest(
                            restored_marker,
                            database.run_marker,
                        )
                        cursor.execute(
                            "SELECT [Value] FROM [ostv_it].[RestoreProbe] "
                            "WHERE [Id]=1"
                        )
                        restored_value = str(cursor.fetchone()[0])
                self.assertTrue(restored_marker_verified)
                self.assertEqual(restored_value, "preserved")
        finally:
            if restored_marker_verified:
                master_request = SqlConnectionRequest(
                    configuration.location,
                    password=configuration.password,
                    database_override="master",
                )
                with database.connections.connection(
                    master_request,
                    autocommit=True,
                ) as lease:
                    with lease.cursor() as cursor:
                        cursor.execute(
                            "EXEC [ostv_it].[DropDatabase] "
                            "@DatabaseName=?, @RunMarker=?, "
                            "@ExpectedServerMarker=?",
                            restored_name,
                            database.run_marker,
                            configuration.server_marker,
                        )
            if backup_path and os.path.exists(backup_path):
                os.remove(backup_path)

    def test_temporary_reader_editor_and_admin_role_boundaries(self):
        configuration = DisposableSqlConfiguration.from_environment()
        suffix = secrets.token_hex(6).upper()
        accounts = {
            f"OSTV_IT_TMP_READER_{suffix}": (
                "reader",
                secrets.token_urlsafe(32),
            ),
            f"OSTV_IT_TMP_EDITOR_{suffix}": (
                "editor",
                secrets.token_urlsafe(32),
            ),
            f"OSTV_IT_TMP_ADMIN_{suffix}": (
                "administrator",
                secrets.token_urlsafe(32),
            ),
        }
        manager = SqlConnectionManager()
        windows_master = replace(
            configuration.location,
            authentication_mode=SqlAuthenticationMode.WINDOWS,
            username="",
        )
        windows_master_request = SqlConnectionRequest(
            windows_master,
            database_override="master",
        )
        with manager.connection(windows_master_request, autocommit=True) as lease:
            with lease.cursor() as cursor:
                for login, (_role, password) in accounts.items():
                    cursor.execute(
                        "DECLARE @secret nvarchar(128)=?; "
                        "DECLARE @statement nvarchar(max)=N'CREATE LOGIN "
                        f"[{login}] WITH PASSWORD=' + "
                        "QUOTENAME(@secret, NCHAR(39)) + "
                        "N', CHECK_POLICY=ON, CHECK_EXPIRATION=OFF'; "
                        "EXEC sys.sp_executesql @statement",
                        password,
                    )
        try:
            with DisposableSqlDatabase(configuration) as database:
                windows_location = replace(
                    database.location,
                    authentication_mode=SqlAuthenticationMode.WINDOWS,
                    username="",
                )
                with database.connections.connection(
                    SqlConnectionRequest(windows_location),
                    autocommit=True,
                ) as lease:
                    with lease.cursor() as cursor:
                        cursor.execute(
                            "CREATE TABLE [dbo].[PermissionProbe] "
                            "([Id] int NOT NULL PRIMARY KEY, [Value] int NOT NULL)"
                        )
                        for login, (account_type, _password) in accounts.items():
                            cursor.execute(f"CREATE USER [{login}] FOR LOGIN [{login}]")
                            if account_type == "reader":
                                cursor.execute(
                                    f"ALTER ROLE [ostv_it_reader] ADD MEMBER [{login}]"
                                )
                            else:
                                apply_sql_client_permissions(cursor, login)
                                if account_type == "administrator":
                                    cursor.execute(
                                        "ALTER ROLE [ostv_it_collaboration_admin] "
                                        f"ADD MEMBER [{login}]"
                                    )
                reader_login, editor_login, administrator_login = accounts
                reader = self._sql_login_request(
                    database,
                    reader_login,
                    accounts[reader_login][1],
                )
                editor = self._sql_login_request(
                    database,
                    editor_login,
                    accounts[editor_login][1],
                )
                administrator = self._sql_login_request(
                    database,
                    administrator_login,
                    accounts[administrator_login][1],
                )
                self.assertEqual(
                    self._database_permissions(database, reader),
                    (1, 0, 0, 0, 0, 1, 1, 0, 0),
                )
                self.assertEqual(
                    self._database_permissions(database, editor),
                    (1, 1, 1, 0, 0, 1, 1, 1, 1),
                )
                self.assertEqual(
                    self._database_permissions(database, administrator),
                    (1, 1, 1, 1, 0, 1, 1, 1, 1),
                )
                with self.assertRaises(SqlInfrastructureError):
                    with database.connections.connection(
                        reader,
                        autocommit=True,
                    ) as lease:
                        with lease.cursor() as cursor:
                            cursor.execute(
                                "INSERT INTO [dbo].[PermissionProbe] "
                                "([Id], [Value]) VALUES (1, 1)"
                            )
                with database.connections.connection(
                    editor,
                    autocommit=True,
                ) as lease:
                    with lease.cursor() as cursor:
                        cursor.execute(
                            "INSERT INTO [dbo].[PermissionProbe] "
                            "([Id], [Value]) VALUES (1, 1); "
                            "UPDATE [dbo].[PermissionProbe] SET [Value]=2 "
                            "WHERE [Id]=1; "
                            "DELETE FROM [dbo].[PermissionProbe] WHERE [Id]=1"
                        )
                with self.assertRaises(SqlInfrastructureError):
                    with database.connections.connection(
                        editor,
                        autocommit=True,
                    ) as lease:
                        with lease.cursor() as cursor:
                            cursor.execute(
                                "CREATE TABLE [dbo].[ForbiddenSchemaChange] "
                                "([Id] int NOT NULL)"
                            )
        finally:
            with manager.connection(
                windows_master_request,
                autocommit=True,
            ) as lease:
                with lease.cursor() as cursor:
                    for login in accounts:
                        cursor.execute(
                            f"IF SUSER_ID(N'{login}') IS NOT NULL "
                            f"DROP LOGIN [{login}]"
                        )

    @staticmethod
    def _sql_login_request(
        database: DisposableSqlDatabase,
        username: str,
        password: str,
    ) -> SqlConnectionRequest:
        location = replace(
            database.location,
            authentication_mode=SqlAuthenticationMode.SQL_SERVER,
            username=username,
        )
        return SqlConnectionRequest(location, password=password)

    @staticmethod
    def _database_permissions(
        database: DisposableSqlDatabase,
        request: SqlConnectionRequest,
    ) -> tuple[int, int, int, int, int, int, int, int, int]:
        with database.connections.connection(request, autocommit=True) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    "SELECT "
                    "HAS_PERMS_BY_NAME(N'dbo.PermissionProbe', N'OBJECT', N'SELECT'), "
                    "HAS_PERMS_BY_NAME(N'dbo.PermissionProbe', N'OBJECT', N'INSERT'), "
                    "HAS_PERMS_BY_NAME(N'ostv.Sessions', N'OBJECT', N'INSERT'), "
                    "HAS_PERMS_BY_NAME(NULL, N'DATABASE', N'VIEW DATABASE STATE'), "
                    "HAS_PERMS_BY_NAME(NULL, N'DATABASE', N'VIEW DEFINITION'), "
                    "HAS_PERMS_BY_NAME(N'dbo', N'SCHEMA', N'VIEW DEFINITION'), "
                    "HAS_PERMS_BY_NAME(N'ostv', N'SCHEMA', N'VIEW DEFINITION'), "
                    "ISNULL(IS_ROLEMEMBER(N'db_datareader'), 0), "
                    "ISNULL(IS_ROLEMEMBER(N'db_datawriter'), 0)"
                )
                return tuple(map(int, cursor.fetchone()))


if __name__ == "__main__":
    unittest.main()
