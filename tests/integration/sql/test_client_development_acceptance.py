import json
import os
import secrets
import subprocess
import unittest
import uuid
from pathlib import Path
from tests.paths import REPO_ROOT
from ost_visualizer.application.dtos.collaboration_dtos import PresenceMode, ResourceRef
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.sql.catalog import SqlDatabaseCatalog
from ost_visualizer.infrastructure.sql.collaboration_store import SqlCollaborationStore
from ost_visualizer.infrastructure.sql.connection_manager import (
    SqlConnectionManager,
    SqlConnectionRequest,
)
from ost_visualizer.infrastructure.sql.credential_store import WindowsCredentialStore
from ost_visualizer.infrastructure.sql.errors import SqlInfrastructureError
from ost_visualizer.infrastructure.sql.permissions import SqlDatabasePermissionProbe
from ost_visualizer.infrastructure.sql.remote_change_reader import SqlRemoteChangeReader
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.infrastructure.sql.schema_inspector import SqlSchemaInspector
from tools.manage_sql_development import DATABASE_MARKER_PROPERTY, read_secrets


def _same_secret(actual, expected) -> bool:
    # Secrets are compared without assertEqual so a failure never prints them.
    return secrets.compare_digest(str(actual).encode(), str(expected).encode())


def _development_location(development) -> SqlServerDatabaseLocation:
    return SqlServerDatabaseLocation(
        server=f"tcp:{development.server}",
        database=development.database,
        authentication_mode=SqlAuthenticationMode.SQL_SERVER,
        username=development.username,
        encrypt=development.encrypt,
        trust_server_certificate=development.trust_server_certificate,
    )


class _RuntimeCredentialStore:
    def __init__(self, password: str) -> None:
        self._password = password

    def read_password(self, _target: str) -> str:
        return self._password

    def write_password(self, _target: str, _username: str, password: str) -> None:
        self._password = password

    def delete_password(self, _target: str) -> None:
        self._password = ""


class SqlClientDevelopmentIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("OSTV_SQL_CLIENT_INTEGRATION") != "1":
            raise unittest.SkipTest(
                "Set OSTV_SQL_CLIENT_INTEGRATION=1 to run client environment tests."
            )
        if os.environ.get("OSTV_SQL_DESTRUCTIVE_TESTS") != "1":
            raise unittest.SkipTest(
                "Set OSTV_SQL_DESTRUCTIVE_TESTS=1 to authorize local SQL mutations."
            )
        cls.secrets_path = REPO_ROOT / ".secrets" / "sql-development.json"
        cls.development = read_secrets(cls.secrets_path)
        if cls.development is None:
            raise unittest.SkipTest("The SQL development secrets file is missing.")
        cls._require_owned_database()

    @classmethod
    def _require_owned_database(cls):
        # Every test below writes sessions, locks or probes: refuse any database
        # that does not carry this environment's ownership marker.
        request = SqlConnectionRequest(
            _development_location(cls.development),
            password=cls.development.password,
            read_only=True,
        )
        with SqlConnectionManager().connection(request, autocommit=True) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    "SELECT CONVERT(nvarchar(128), value) FROM "
                    "sys.extended_properties WHERE class=0 AND name=?",
                    DATABASE_MARKER_PROPERTY,
                )
                row = cursor.fetchone()
        if row is None or not _same_secret(row[0], cls.development.ownership_marker):
            raise RuntimeError(
                "Refusing client integration tests: the SQL development database "
                "ownership marker is missing or invalid."
            )

    def test_secrets_file_acl_is_restricted(self):
        command = (
            "$acl=Get-Acl -LiteralPath '"
            + str(self.secrets_path).replace("'", "''")
            + "'; $sids=@($acl.Access | ForEach-Object {"
            "$_.IdentityReference.Translate("
            "[Security.Principal.SecurityIdentifier]).Value}); "
            "$current=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value; "
            "[pscustomobject]@{Protected=$acl.AreAccessRulesProtected;"
            "Current=$current;Sids=$sids}|ConvertTo-Json -Compress"
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertTrue(result["Protected"])
        self.assertEqual(set(result["Sids"]), {result["Current"], "S-1-5-32-544"})

    def test_credential_manager_round_trip_and_persistent_client_secret(self):
        store = WindowsCredentialStore()
        temporary_target = "OSTVisualizer/Development/OSTVDEV/Test/" + uuid.uuid4().hex
        temporary_password = secrets.token_urlsafe(32)
        try:
            store.write_password(
                temporary_target, "temporary-test-user", temporary_password
            )
            self.assertTrue(
                _same_secret(store.read_password(temporary_target), temporary_password),
                "The temporary credential did not round-trip.",
            )
        finally:
            store.delete_password(temporary_target)
        self.assertTrue(
            store.read_password(temporary_target) is None,
            "The temporary credential remained after deletion.",
        )
        self.assertTrue(
            _same_secret(
                store.read_password(self.development.credential_target),
                self.development.password,
            ),
            "The persistent client credential does not match the secrets file.",
        )

    def test_client_login_is_least_privilege_and_schema_is_current(self):
        location = self._location()
        inventory = SqlSchemaInspector().inspect(location, self.development.password)
        self.assertEqual(inventory.schema_version, SQL_SCHEMA_V1.version)
        self.assertEqual(inventory.schema_checksum, SQL_SCHEMA_V1.checksum)
        manager = SqlConnectionManager()
        request = SqlConnectionRequest(location, password=self.development.password)
        with manager.connection(request, autocommit=True) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    "SELECT IS_SRVROLEMEMBER(N'sysadmin'), "
                    "IS_SRVROLEMEMBER(N'dbcreator'), "
                    "COALESCE(HAS_PERMS_BY_NAME(NULL, NULL, "
                    "N'CREATE ANY DATABASE'), 0), "
                    "HAS_PERMS_BY_NAME(NULL, N'DATABASE', N'ALTER'), "
                    "HAS_PERMS_BY_NAME(NULL, N'DATABASE', N'VIEW DEFINITION'), "
                    "HAS_PERMS_BY_NAME(N'dbo', N'SCHEMA', N'VIEW DEFINITION'), "
                    "HAS_PERMS_BY_NAME(N'ostv', N'SCHEMA', N'VIEW DEFINITION'), "
                    "HAS_PERMS_BY_NAME(N'dbo.Settings', N'OBJECT', N'SELECT'), "
                    "HAS_PERMS_BY_NAME(N'dbo.Settings', N'OBJECT', N'UPDATE'), "
                    "IS_ROLEMEMBER(N'db_datareader'), "
                    "IS_ROLEMEMBER(N'db_datawriter'), "
                    "HAS_PERMS_BY_NAME(N'ostv.DatabaseMetadata', N'OBJECT', "
                    "N'UPDATE'), "
                    "HAS_PERMS_BY_NAME(N'ostv.SchemaMigrations', N'OBJECT', "
                    "N'INSERT'), "
                    "HAS_PERMS_BY_NAME(N'ostv.ExternalAdapterState', N'OBJECT', "
                    "N'DELETE')"
                )
                permissions = tuple(map(int, cursor.fetchone()))
                cursor.execute(
                    "SELECT CASE WHEN DATABASE_PRINCIPAL_ID(N'ostv_client_editor') "
                    "IS NULL THEN 0 ELSE 1 END"
                )
                obsolete_role_exists = bool(cursor.fetchone()[0])
                cursor.execute(
                    "SELECT CONVERT(nvarchar(128), value) FROM "
                    "sys.extended_properties WHERE class=0 AND name=?",
                    DATABASE_MARKER_PROPERTY,
                )
                marker = str(cursor.fetchone()[0])
        self.assertEqual(
            permissions,
            (0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 0, 0, 0),
        )
        self.assertFalse(obsolete_role_exists)
        self.assertTrue(
            _same_secret(marker, self.development.ownership_marker),
            "The database ownership marker does not match the secrets file.",
        )
        try:
            with self.assertRaises(SqlInfrastructureError):
                with manager.connection(request, autocommit=False) as lease:
                    with lease.cursor() as cursor:
                        cursor.execute(
                            "CREATE TABLE [dbo].[ForbiddenClientDdl] ([Id] int)"
                        )
        finally:
            with manager.connection(request, autocommit=True) as lease:
                with lease.cursor() as cursor:
                    cursor.execute(
                        "SELECT CASE WHEN OBJECT_ID(N'dbo.ForbiddenClientDdl') "
                        "IS NULL THEN 0 ELSE 1 END"
                    )
                    self.assertEqual(int(cursor.fetchone()[0]), 0)

    def test_client_catalog_recognizes_the_canonical_schema(self):
        entry = SqlDatabaseCatalog().get_database(
            self._location(),
            self.development.database,
            self.development.password,
        )
        self.assertTrue(entry.is_compatible, entry.compatibility_message)
        self.assertEqual(entry.schema_version, SQL_SCHEMA_V1.version)

    def test_client_permission_probe_accepts_the_canonical_role_model(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            self._location(),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry = DatabaseDescriptorRegistry()
        registry.register(descriptor)
        probe = SqlDatabasePermissionProbe(
            registry,
            _RuntimeCredentialStore(self.development.password),
        )
        self.assertTrue(probe.can_edit(descriptor.database_id))

    def test_client_session_heartbeat_lock_and_rollback_cleanup(self):
        location = self._location()
        descriptor = DatabaseDescriptor.for_sql_server(
            location,
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry = DatabaseDescriptorRegistry()
        registry.register(descriptor)
        credentials = _RuntimeCredentialStore(self.development.password)
        remote_reader = SqlRemoteChangeReader(registry, credentials)
        store = SqlCollaborationStore(registry, credentials, remote_reader)
        session = store.start_session(
            descriptor.database_id,
            str(uuid.uuid4()),
            str(uuid.uuid4()),
            "persistent-client-test",
            "local-development",
            "integration-test",
        )
        lock = None
        try:
            store.heartbeat(
                descriptor.database_id,
                session.session_id,
                0,
                None,
                None,
                PresenceMode.VIEWING,
            )
            resource = ResourceRef("database", descriptor.database_id)
            lock = store.acquire_locks(
                descriptor.database_id,
                session.session_id,
                (resource,),
                "persistent client verification",
            )[0]
            manager = SqlConnectionManager()
            request = SqlConnectionRequest(
                location,
                password=self.development.password,
            )
            with manager.connection(request, autocommit=False) as lease:
                with lease.cursor() as cursor:
                    cursor.execute(
                        "UPDATE [ostv].[Presence] SET [ActivityMode]=N'editing' "
                        "WHERE [SessionId]=?",
                        session.session_id,
                    )
                    # Positive control: the rolled-back statement really matched.
                    self.assertEqual(cursor.rowcount, 1)
                lease.rollback()
            with manager.connection(request, autocommit=True) as lease:
                with lease.cursor() as cursor:
                    cursor.execute(
                        "SELECT [ActivityMode] FROM [ostv].[Presence] "
                        "WHERE [SessionId]=?",
                        session.session_id,
                    )
                    self.assertEqual(
                        str(cursor.fetchone()[0]), PresenceMode.VIEWING.value
                    )
        finally:
            if lock is not None:
                store.release_lock(
                    descriptor.database_id,
                    session.session_id,
                    lock.lock_token,
                )
            store.close_session(
                descriptor.database_id,
                session.session_id,
                "persistent-client-test-complete",
            )
        manager = SqlConnectionManager()
        request = SqlConnectionRequest(
            location,
            password=self.development.password,
            read_only=True,
        )
        with manager.connection(request, autocommit=True) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    "SELECT "
                    "(SELECT COUNT(*) FROM [ostv].[Presence] WHERE [SessionId]=?), "
                    "(SELECT COUNT(*) FROM [ostv].[Locks] WHERE [OwnerSessionId]=?), "
                    "(SELECT COUNT(*) FROM [ostv].[Sessions] WHERE [SessionId]=? "
                    "AND [DisconnectedAt] IS NULL)",
                    session.session_id,
                    session.session_id,
                    session.session_id,
                )
                self.assertEqual(tuple(map(int, cursor.fetchone())), (0, 0, 0))

    def _location(self):
        return _development_location(self.development)


if __name__ == "__main__":
    unittest.main()
