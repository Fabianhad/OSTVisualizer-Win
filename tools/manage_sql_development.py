from __future__ import annotations
import argparse
import json
import os
import secrets
import socket
import uuid
import winreg
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import pyodbc
from ost_visualizer.domain.entities.database_descriptor import (
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.sql.connection_manager import (
    SqlConnectionManager,
    SqlConnectionRequest,
)
from ost_visualizer.infrastructure.sql.client_permissions import (
    SQL_CLIENT_DATABASE_ROLES,
    SQL_CLIENT_PROTECTED_OSTV_TABLES,
    SQL_CLIENT_SCHEMA_VISIBILITY,
    apply_sql_client_permissions,
)
from ost_visualizer.infrastructure.sql.credential_store import WindowsCredentialStore
from ost_visualizer.infrastructure.sql.database_creator import SqlDatabaseCreator
from ost_visualizer.infrastructure.sql.errors import SqlInfrastructureError
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.infrastructure.sql.schema_inspector import SqlSchemaInspector
from ost_visualizer.infrastructure.sql.schema_validator import SqlSchemaValidator

SERVER_HOST = socket.gethostname()
SERVER_PORT = 1433
SERVER_ENDPOINT = f"tcp:{SERVER_HOST}"
INSTANCE_NAME = "OSTVDEV"
CLIENT_DATABASE = "OSTV_CLIENT_TEST"
CLIENT_LOGIN = "OSTV_CLIENT_TEST_USER"
CLIENT_CREDENTIAL_TARGET = "OSTVisualizer/Development/OSTVDEV/Client"
INTEGRATION_LOGIN = "OSTV_IT_EXECUTOR"
INTEGRATION_CREDENTIAL_TARGET = "OSTVisualizer/Integration/OSTVDEV/Executor"
ENVIRONMENT_MARKER_PROPERTY = "OSTVisualizerSqlDevelopmentEnvironment"
DATABASE_MARKER_PROPERTY = "OSTVisualizerSqlDevelopmentDatabase"
DISPOSABLE_MARKER_PROPERTY = "OSTVisualizerDisposableTestRun"
REGISTRY_PATH = r"SOFTWARE\OSTVisualizer\SqlDevelopment"
SECRETS_FILE_NAME = "sql-development.json"
_SECRET_KEYS = (
    "server",
    "port",
    "database",
    "authentication_mode",
    "username",
    "password",
    "credential_target",
    "encrypt",
    "trust_server_certificate",
    "ownership_marker",
)


@dataclass(frozen=True, repr=False)
class SqlDevelopmentSecrets:
    server: str
    port: int
    database: str
    authentication_mode: str
    username: str
    password: str
    credential_target: str
    encrypt: bool
    trust_server_certificate: bool
    ownership_marker: str

    def __repr__(self) -> str:
        return (
            "SqlDevelopmentSecrets(connection=<redacted>, password=<redacted>, "
            "ownership_marker=<redacted>)"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "server": self.server,
            "port": self.port,
            "database": self.database,
            "authentication_mode": self.authentication_mode,
            "username": self.username,
            "password": self.password,
            "credential_target": self.credential_target,
            "encrypt": self.encrypt,
            "trust_server_certificate": self.trust_server_certificate,
            "ownership_marker": self.ownership_marker,
        }


@dataclass(frozen=True)
class PasswordSelection:
    password: str
    rotate_login: bool


@dataclass(frozen=True)
class TeardownInventory:
    owned_databases: tuple[str, ...]
    unowned_databases: tuple[str, ...]
    unexpected_logins: tuple[str, ...]
    active_sessions: int
    pending_restores: int


def generate_client_password() -> str:
    return secrets.token_urlsafe(48)


def select_client_password(
    existing_password: str,
    *,
    login_exists: bool,
    existing_password_works: bool,
    rotate_requested: bool,
) -> PasswordSelection:
    if rotate_requested:
        return PasswordSelection(generate_client_password(), True)
    if login_exists:
        if not existing_password or not existing_password_works:
            raise RuntimeError(
                "The owned client login exists but its stored credential is invalid. "
                "Use -RotateClientPassword to repair it explicitly."
            )
        return PasswordSelection(existing_password, False)
    return PasswordSelection(generate_client_password(), True)


def validate_database_ownership(
    *, database_exists: bool, actual_marker: str, expected_marker: str
) -> None:
    if database_exists and (
        not actual_marker or not secrets.compare_digest(actual_marker, expected_marker)
    ):
        raise RuntimeError(
            "The requested client database exists without the expected ownership "
            "marker; no changes were made to it."
        )


def validate_teardown_inventory(inventory: TeardownInventory) -> None:
    if inventory.unowned_databases:
        raise RuntimeError("Teardown found an unmarked or unrelated user database.")
    if inventory.unexpected_logins:
        raise RuntimeError("Teardown found an unrelated server login.")
    if inventory.active_sessions:
        raise RuntimeError("Teardown found an active session using an owned resource.")
    if inventory.pending_restores:
        raise RuntimeError("Teardown found a pending disposable database restore.")


def write_secrets_atomic(path: Path, value: SqlDevelopmentSecrets) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            descriptor = -1
            json.dump(value.to_dict(), stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def read_secrets(path: Path) -> Optional[SqlDevelopmentSecrets]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("The SQL development secrets file is unreadable.") from exc
    if not isinstance(payload, dict) or set(payload) != set(_SECRET_KEYS):
        raise RuntimeError("The SQL development secrets file has an invalid shape.")
    string_keys = set(_SECRET_KEYS) - {
        "port",
        "encrypt",
        "trust_server_certificate",
    }
    if (
        any(not isinstance(payload[key], str) for key in string_keys)
        or type(payload["port"]) is not int
        or type(payload["encrypt"]) is not bool
        or type(payload["trust_server_certificate"]) is not bool
    ):
        raise RuntimeError("The SQL development secrets file has invalid value types.")
    value = SqlDevelopmentSecrets(
        server=payload["server"],
        port=payload["port"],
        database=payload["database"],
        authentication_mode=payload["authentication_mode"],
        username=payload["username"],
        password=payload["password"],
        credential_target=payload["credential_target"],
        encrypt=payload["encrypt"],
        trust_server_certificate=payload["trust_server_certificate"],
        ownership_marker=payload["ownership_marker"],
    )
    _validate_secret_constants(value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manage the owned local OST Visualizer SQL client environment."
    )
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--provision", action="store_true")
    actions.add_argument("--verify-teardown", action="store_true")
    actions.add_argument("--prepare-teardown", action="store_true")
    actions.add_argument("--complete-teardown", action="store_true")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--rotate-client-password", action="store_true")
    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve()
    secrets_path = _validated_secrets_path(repo_root)
    if args.provision:
        result = _provision(secrets_path, args.rotate_client_password)
    elif args.verify_teardown:
        result = _verify_teardown(secrets_path)
    elif args.prepare_teardown:
        result = _prepare_teardown(secrets_path)
    else:
        result = _complete_teardown(secrets_path)
    print(json.dumps(result, sort_keys=True))
    return 0


def _provision(secrets_path: Path, rotate_requested: bool) -> dict[str, object]:
    existing_secrets = read_secrets(secrets_path)
    credential_store = WindowsCredentialStore()
    credential_password = credential_store.read_password(CLIENT_CREDENTIAL_TARGET) or ""
    connection = _windows_connection()
    password = ""
    previous_password = ""
    try:
        require_owned_sql_instance(connection)
        ownership_preexisting = _registry_exists() or existing_secrets is not None
        marker = _resolve_ownership_marker(connection, existing_secrets)
        _validate_registry_ownership(marker)
        login_exists = _login_exists(connection, CLIENT_LOGIN)
        if not ownership_preexisting and login_exists:
            raise RuntimeError(
                "The requested client login exists without a setup ownership record."
            )
        if not ownership_preexisting and credential_password:
            raise RuntimeError(
                "The client credential target exists without a setup ownership record."
            )
        database_created = _ensure_database_container(connection, marker)
        location = _windows_location(CLIENT_DATABASE)
        _ensure_canonical_schema(location)
        _write_registry_ownership(marker, _installer_principal())
        previous_password = credential_password or (
            existing_secrets.password if existing_secrets is not None else ""
        )
        password_works = bool(previous_password) and _client_login_accepts(
            previous_password
        )
        selection = select_client_password(
            previous_password,
            login_exists=login_exists,
            existing_password_works=password_works,
            rotate_requested=rotate_requested,
        )
        password = selection.password
        _configure_client_login_and_permissions(
            connection,
            password,
            update_password=selection.rotate_login,
        )
        try:
            credential_store.write_password(
                CLIENT_CREDENTIAL_TARGET, CLIENT_LOGIN, password
            )
        except OSError:
            if login_exists and previous_password and selection.rotate_login:
                _set_login_password(connection, previous_password)
            raise
        value = SqlDevelopmentSecrets(
            server=SERVER_HOST,
            port=SERVER_PORT,
            database=CLIENT_DATABASE,
            authentication_mode="sql",
            username=CLIENT_LOGIN,
            password=password,
            credential_target=CLIENT_CREDENTIAL_TARGET,
            encrypt=True,
            trust_server_certificate=False,
            ownership_marker=marker,
        )
        write_secrets_atomic(secrets_path, value)
        inventory = SqlSchemaInspector().inspect(location)
        return {
            "status": "configured",
            "database_created": database_created,
            "credential_rotated": selection.rotate_login,
            "schema_version": inventory.schema_version,
            "schema_checksum_valid": (
                inventory.schema_checksum == SQL_SCHEMA_V1.checksum
            ),
            "ownership_marker_configured": True,
        }
    finally:
        connection.close()
        credential_password = ""
        previous_password = ""
        password = ""


def _verify_teardown(secrets_path: Path) -> dict[str, object]:
    stored = _required_owned_secrets(secrets_path)
    connection = _windows_connection()
    try:
        require_owned_sql_instance(connection)
        _require_server_marker(connection, stored.ownership_marker)
        inventory = _collect_teardown_inventory(connection, stored.ownership_marker)
        validate_teardown_inventory(inventory)
    finally:
        connection.close()
    return {
        "status": "verified",
        "owned_database_count": len(inventory.owned_databases),
        "safe_for_instance_removal": True,
    }


def _prepare_teardown(secrets_path: Path) -> dict[str, object]:
    stored = _required_owned_secrets(secrets_path)
    connection = _windows_connection()
    try:
        require_owned_sql_instance(connection)
        _require_server_marker(connection, stored.ownership_marker)
        inventory = _collect_teardown_inventory(connection, stored.ownership_marker)
        validate_teardown_inventory(inventory)
        for database_name in inventory.owned_databases:
            _drop_verified_owned_database(
                connection, database_name, stored.ownership_marker
            )
        _remove_owned_master_objects(connection)
    finally:
        connection.close()
    return {"status": "prepared", "sql_resources_removed": True}


def _complete_teardown(secrets_path: Path) -> dict[str, object]:
    stored = _required_owned_secrets(secrets_path)
    current = read_secrets(secrets_path)
    if current is None or not secrets.compare_digest(
        current.ownership_marker, stored.ownership_marker
    ):
        raise RuntimeError("The secrets ownership marker changed during teardown.")
    credential_store = WindowsCredentialStore()
    credential_store.delete_password(CLIENT_CREDENTIAL_TARGET)
    credential_store.delete_password(INTEGRATION_CREDENTIAL_TARGET)
    _remove_user_environment()
    secrets_path.unlink()
    return {"status": "completed", "credentials_removed": True}


def _resolve_ownership_marker(
    connection, existing_secrets: Optional[SqlDevelopmentSecrets]
) -> str:
    sql_marker = _server_property(connection, ENVIRONMENT_MARKER_PROPERTY)
    registry_marker = _registry_value("OwnershipMarker")
    file_marker = existing_secrets.ownership_marker if existing_secrets else ""
    markers = tuple(
        value for value in (sql_marker, registry_marker, file_marker) if value
    )
    if len(set(markers)) > 1:
        raise RuntimeError("SQL development ownership markers do not agree.")
    marker = markers[0] if markers else str(uuid.uuid4())
    try:
        uuid.UUID(marker)
    except ValueError as exc:
        raise RuntimeError("The SQL development ownership marker is invalid.") from exc
    _set_server_property(connection, ENVIRONMENT_MARKER_PROPERTY, marker)
    return marker


def _ensure_database_container(connection, marker: str) -> bool:
    exists = _database_exists(connection, CLIENT_DATABASE)
    actual_marker = _database_marker(connection, CLIENT_DATABASE) if exists else ""
    validate_database_ownership(
        database_exists=exists,
        actual_marker=actual_marker,
        expected_marker=marker,
    )
    if exists:
        return False
    cursor = connection.cursor()
    try:
        cursor.execute(f"CREATE DATABASE [{CLIENT_DATABASE}]")
        cursor.execute(
            f"EXEC [{CLIENT_DATABASE}].sys.sp_addextendedproperty " "@name=?, @value=?",
            DATABASE_MARKER_PROPERTY,
            marker,
        )
    finally:
        cursor.close()
    return True


def _ensure_canonical_schema(location: SqlServerDatabaseLocation) -> None:
    inspector = SqlSchemaInspector()
    inventory = inspector.inspect(location)
    if inventory.schema_version == 0 and not any(
        schema in {"dbo", "ostv"} for schema, _table in inventory.tables
    ):
        SqlDatabaseCreator().initialize_blank_database(
            location,
            application_version="development-setup",
            actor="OST Visualizer SQL development setup",
        )
        inventory = inspector.inspect(location)
    report = SqlSchemaValidator(SQL_SCHEMA_V1.core_schema).validate(inventory)
    if not report.is_valid:
        raise RuntimeError("The persistent client database is not canonical schema v1.")


def _configure_client_login_and_permissions(
    connection, password: str, *, update_password: bool
) -> None:
    if update_password:
        _set_login_password(connection, password)
    cursor = connection.cursor()
    try:
        cursor.execute(
            f"ALTER LOGIN [{CLIENT_LOGIN}] ENABLE; "
            f"ALTER LOGIN [{CLIENT_LOGIN}] WITH DEFAULT_DATABASE=[{CLIENT_DATABASE}]"
        )
    finally:
        cursor.close()
    target = pyodbc.connect(
        _windows_connection_string(CLIENT_DATABASE), autocommit=False
    )
    committed = False
    try:
        cursor = target.cursor()
        try:
            cursor.execute(
                f"IF USER_ID(N'{CLIENT_LOGIN}') IS NULL "
                f"CREATE USER [{CLIENT_LOGIN}] FOR LOGIN [{CLIENT_LOGIN}]"
            )
            apply_sql_client_permissions(cursor, CLIENT_LOGIN)
            _verify_client_permissions(cursor)
            target.commit()
            committed = True
        finally:
            cursor.close()
    finally:
        if not committed:
            target.rollback()
        target.close()


def _verify_client_permissions(cursor) -> None:
    role_membership = ", ".join(
        "ISNULL(IS_ROLEMEMBER(?, ?), 0)" for _ in SQL_CLIENT_DATABASE_ROLES
    )
    visible_schemas = ", ".join("?" for _ in SQL_CLIENT_SCHEMA_VISIBILITY)
    protected_tables = ", ".join("?" for _ in SQL_CLIENT_PROTECTED_OSTV_TABLES)
    role_parameters = tuple(
        value for role in SQL_CLIENT_DATABASE_ROLES for value in (role, CLIENT_LOGIN)
    )
    cursor.execute(
        f"SELECT {role_membership}, "
        "(SELECT COUNT(DISTINCT s.name) FROM sys.database_permissions p "
        "JOIN sys.schemas s ON s.schema_id=p.major_id "
        "WHERE p.class_desc=N'SCHEMA' AND p.grantee_principal_id="
        "DATABASE_PRINCIPAL_ID(?) AND p.permission_name=N'VIEW DEFINITION' "
        "AND p.state IN (N'G', N'W') "
        f"AND s.name IN ({visible_schemas})), "
        "(SELECT COUNT(*) FROM sys.database_permissions p "
        "JOIN sys.tables t ON t.object_id=p.major_id "
        "JOIN sys.schemas s ON s.schema_id=t.schema_id "
        "WHERE p.class_desc=N'OBJECT_OR_COLUMN' AND p.grantee_principal_id="
        "DATABASE_PRINCIPAL_ID(?) AND p.permission_name IN "
        "(N'INSERT', N'UPDATE', N'DELETE') AND p.state=N'D' "
        f"AND s.name=N'ostv' AND t.name IN ({protected_tables}))",
        *role_parameters,
        CLIENT_LOGIN,
        *SQL_CLIENT_SCHEMA_VISIBILITY,
        CLIENT_LOGIN,
        *SQL_CLIENT_PROTECTED_OSTV_TABLES,
    )
    expected_denials = 3 * len(SQL_CLIENT_PROTECTED_OSTV_TABLES)
    expected = (
        *(1 for _ in SQL_CLIENT_DATABASE_ROLES),
        len(SQL_CLIENT_SCHEMA_VISIBILITY),
        expected_denials,
    )
    if tuple(map(int, cursor.fetchone())) != expected:
        raise RuntimeError("The client database roles were not applied.")


def _set_login_password(connection, password: str) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "DECLARE @secret nvarchar(128)=?; "
            "DECLARE @statement nvarchar(max); "
            f"IF SUSER_ID(N'{CLIENT_LOGIN}') IS NULL "
            "SET @statement=N'CREATE LOGIN "
            f"[{CLIENT_LOGIN}] WITH PASSWORD=' + QUOTENAME(@secret, NCHAR(39)) + "
            "N', CHECK_POLICY=ON, CHECK_EXPIRATION=OFF, "
            f"DEFAULT_DATABASE=[{CLIENT_DATABASE}]'; "
            "ELSE SET @statement=N'ALTER LOGIN "
            f"[{CLIENT_LOGIN}] WITH PASSWORD=' + QUOTENAME(@secret, NCHAR(39)); "
            "EXEC sys.sp_executesql @statement;",
            password,
        )
    finally:
        cursor.close()


def _collect_teardown_inventory(connection, marker: str) -> TeardownInventory:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT [name] FROM sys.databases WHERE database_id>4 ORDER BY [name]"
        )
        database_names = tuple(str(row[0]) for row in cursor.fetchall())
        owned = []
        unowned = []
        for database_name in database_names:
            if database_name == CLIENT_DATABASE:
                database_marker = _database_marker(
                    connection, database_name, DATABASE_MARKER_PROPERTY
                )
                if database_marker and secrets.compare_digest(database_marker, marker):
                    owned.append(database_name)
                else:
                    unowned.append(database_name)
            elif database_name.startswith("OSTV_IT_"):
                run_marker = _database_marker(
                    connection, database_name, DISPOSABLE_MARKER_PROPERTY
                )
                (owned if run_marker else unowned).append(database_name)
            else:
                unowned.append(database_name)
        current_login = _current_login_name(connection)
        cursor.execute(
            "SELECT [name] FROM sys.server_principals WHERE [type] IN "
            "(N'S',N'U',N'G',N'C') AND is_fixed_role=0 AND [name]<>N'sa' "
            "AND [name] NOT LIKE N'##MS[_]%'"
        )
        allowed = {
            current_login,
            _registry_value("InstallerPrincipal"),
            CLIENT_LOGIN,
            INTEGRATION_LOGIN,
            "OSTV_IT_ProvisioningCertificateLogin",
            r"NT SERVICE\SQLWriter",
            r"NT SERVICE\Winmgmt",
            r"NT Service\MSSQL$OSTVDEV",
            r"NT AUTHORITY\SYSTEM",
            r"NT SERVICE\SQLAgent$OSTVDEV",
            r"NT SERVICE\SQLTELEMETRY$OSTVDEV",
        }
        unexpected_logins = tuple(
            sorted(
                str(row[0])
                for row in cursor.fetchall()
                if str(row[0]) not in allowed
                and not str(row[0]).startswith("OSTV_IT_TMP_")
            )
        )
        cursor.execute(
            "SELECT COUNT(*) FROM sys.dm_exec_sessions WHERE session_id<>@@SPID "
            "AND (login_name IN (?,?) OR login_name LIKE N'OSTV_IT_TMP[_]%' "
            "OR database_id IN (SELECT database_id FROM sys.databases "
            "WHERE database_id>4))",
            CLIENT_LOGIN,
            INTEGRATION_LOGIN,
        )
        active_sessions = int(cursor.fetchone()[0])
        cursor.execute("SELECT COUNT(*) FROM [ostv_it].[PendingRestores]")
        pending_restores = int(cursor.fetchone()[0])
    finally:
        cursor.close()
    return TeardownInventory(
        tuple(owned),
        tuple(unowned),
        unexpected_logins,
        active_sessions,
        pending_restores,
    )


def _drop_verified_owned_database(
    connection, database_name: str, environment_marker: str
) -> None:
    if database_name == CLIENT_DATABASE:
        marker_property = DATABASE_MARKER_PROPERTY
        expected_marker = environment_marker
    elif database_name.startswith("OSTV_IT_"):
        marker_property = DISPOSABLE_MARKER_PROPERTY
        expected_marker = _database_marker(connection, database_name, marker_property)
    else:
        raise RuntimeError("Refusing to remove a database outside the owned scope.")
    actual_marker = _database_marker(connection, database_name, marker_property)
    if not actual_marker or not secrets.compare_digest(actual_marker, expected_marker):
        raise RuntimeError("A database ownership marker changed during teardown.")
    quoted = "[" + database_name.replace("]", "]]") + "]"
    cursor = connection.cursor()
    try:
        cursor.execute(
            f"ALTER DATABASE {quoted} SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
            f"DROP DATABASE {quoted}"
        )
    finally:
        cursor.close()


def _remove_owned_master_objects(connection) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT [name] FROM sys.server_principals WHERE "
            "[name] COLLATE Latin1_General_100_BIN2 LIKE N'OSTV_IT_TMP[_]%'"
        )
        temporary_logins = tuple(str(row[0]) for row in cursor.fetchall())
        for login_name in temporary_logins:
            if not login_name.startswith("OSTV_IT_TMP_") or not all(
                character.isascii() and (character.isalnum() or character == "_")
                for character in login_name
            ):
                raise RuntimeError("A temporary login name is outside the owned scope.")
            cursor.execute(f"DROP LOGIN [{login_name}]")
        cursor.execute(
            f"IF SUSER_ID(N'{CLIENT_LOGIN}') IS NOT NULL DROP LOGIN [{CLIENT_LOGIN}]; "
            f"IF USER_ID(N'{INTEGRATION_LOGIN}') IS NOT NULL "
            f"DROP USER [{INTEGRATION_LOGIN}]; "
            "DROP PROCEDURE IF EXISTS [ostv_it].[CreateDatabase]; "
            "DROP PROCEDURE IF EXISTS [ostv_it].[DropDatabase]; "
            "DROP PROCEDURE IF EXISTS [ostv_it].[RestoreDatabase]; "
            "DROP PROCEDURE IF EXISTS [ostv_it].[ValidateRestoredDatabase]; "
            "DROP TABLE IF EXISTS [ostv_it].[PendingRestores]; "
            "IF SUSER_ID(N'OSTV_IT_ProvisioningCertificateLogin') IS NOT NULL "
            "DROP LOGIN [OSTV_IT_ProvisioningCertificateLogin]; "
            "IF CERT_ID(N'OSTV_IT_ProvisioningCertificate') IS NOT NULL "
            "DROP CERTIFICATE [OSTV_IT_ProvisioningCertificate]; "
            f"IF SUSER_ID(N'{INTEGRATION_LOGIN}') IS NOT NULL "
            f"DROP LOGIN [{INTEGRATION_LOGIN}]; "
            "IF SCHEMA_ID(N'ostv_it') IS NOT NULL DROP SCHEMA [ostv_it]"
        )
        for property_name in (
            ENVIRONMENT_MARKER_PROPERTY,
            "OSTVisualizerDisposableTestServer",
            "OSTVisualizerDisposableBackupRoot",
        ):
            cursor.execute(
                "IF EXISTS (SELECT 1 FROM sys.extended_properties WHERE class=0 "
                "AND name=?) EXEC sys.sp_dropextendedproperty @name=?",
                property_name,
                property_name,
            )
    finally:
        cursor.close()


def _required_owned_secrets(path: Path) -> SqlDevelopmentSecrets:
    stored = read_secrets(path)
    if stored is None:
        raise RuntimeError("The owned SQL development secrets file is missing.")
    marker = _registry_value("OwnershipMarker")
    if not marker or not secrets.compare_digest(marker, stored.ownership_marker):
        raise RuntimeError("The registry and secrets ownership markers do not agree.")
    _validate_registry_ownership(marker)
    return stored


def _validate_secret_constants(value: SqlDevelopmentSecrets) -> None:
    if (
        value.server != SERVER_HOST
        or value.port != SERVER_PORT
        or value.database != CLIENT_DATABASE
        or value.authentication_mode != "sql"
        or value.username != CLIENT_LOGIN
        or value.credential_target != CLIENT_CREDENTIAL_TARGET
        or not value.encrypt
        or value.trust_server_certificate
    ):
        raise RuntimeError("The SQL development secrets identity is invalid.")
    if not value.password:
        raise RuntimeError("The SQL development password is missing.")
    try:
        uuid.UUID(value.ownership_marker)
    except ValueError as exc:
        raise RuntimeError("The SQL development ownership marker is invalid.") from exc


def _validate_registry_ownership(marker: str) -> None:
    if not _registry_exists():
        return
    expected = {
        "OwnershipMarker": marker,
        "InstanceName": INSTANCE_NAME,
        "DatabaseName": CLIENT_DATABASE,
        "ClientLogin": CLIENT_LOGIN,
        "ClientCredentialTarget": CLIENT_CREDENTIAL_TARGET,
        "IntegrationCredentialTarget": INTEGRATION_CREDENTIAL_TARGET,
    }
    for name, value in expected.items():
        if _registry_value(name) != value:
            raise RuntimeError("The SQL development registry ownership is invalid.")


def _write_registry_ownership(marker: str, installer_principal: str) -> None:
    with winreg.CreateKeyEx(
        winreg.HKEY_LOCAL_MACHINE,
        REGISTRY_PATH,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        values = {
            "OwnershipMarker": marker,
            "InstanceName": INSTANCE_NAME,
            "DatabaseName": CLIENT_DATABASE,
            "ClientLogin": CLIENT_LOGIN,
            "ClientCredentialTarget": CLIENT_CREDENTIAL_TARGET,
            "IntegrationCredentialTarget": INTEGRATION_CREDENTIAL_TARGET,
            "InstallerPrincipal": installer_principal,
        }
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def _registry_exists() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_PATH):
            return True
    except FileNotFoundError:
        return False


def _registry_value(name: str) -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_PATH) as key:
            value, _value_type = winreg.QueryValueEx(key, name)
            return str(value)
    except FileNotFoundError:
        return ""


def _remove_user_environment() -> None:
    names = (
        "OSTV_SQL_TEST_SERVER",
        "OSTV_SQL_TEST_AUTH",
        "OSTV_SQL_TEST_USER",
        "OSTV_SQL_TEST_SERVER_MARKER",
        "OSTV_SQL_TEST_CREDENTIAL_TARGET",
        "OSTV_SQL_INTEGRATION",
        "OSTV_SQL_DESTRUCTIVE_TESTS",
        "OSTV_SQL_TEST_PASSWORD",
    )
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE
    ) as key:
        for name in names:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass


def _validated_secrets_path(repo_root: Path) -> Path:
    if not (repo_root / "ost_visualizer").is_dir():
        raise ValueError("Repo root does not identify OST Visualizer.")
    return repo_root / ".secrets" / SECRETS_FILE_NAME


def _windows_location(database: str) -> SqlServerDatabaseLocation:
    return SqlServerDatabaseLocation(
        server=SERVER_ENDPOINT,
        database=database,
        authentication_mode=SqlAuthenticationMode.WINDOWS,
        encrypt=True,
        trust_server_certificate=False,
    )


def _windows_connection_string(database: str = "master") -> str:
    return (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={{{SERVER_ENDPOINT}}};DATABASE={{{database}}};"
        "Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=no;"
        "Connection Timeout=10;MARS_Connection=no;"
        "APP=OST Visualizer SQL Development Manager;"
    )


def _windows_connection():
    return pyodbc.connect(_windows_connection_string(), autocommit=True, timeout=10)


def require_owned_sql_instance(connection) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT CONVERT(nvarchar(128), SERVERPROPERTY('InstanceName'))")
        row = cursor.fetchone()
    finally:
        cursor.close()
    if row is None or str(row[0]).casefold() != INSTANCE_NAME.casefold():
        raise RuntimeError(
            "The configured endpoint is not the dedicated OSTVDEV SQL instance."
        )


def _client_login_accepts(password: str) -> bool:
    location = SqlServerDatabaseLocation(
        server=SERVER_ENDPOINT,
        database=CLIENT_DATABASE,
        authentication_mode=SqlAuthenticationMode.SQL_SERVER,
        username=CLIENT_LOGIN,
        encrypt=True,
        trust_server_certificate=False,
    )
    manager = SqlConnectionManager()
    try:
        with manager.connection(
            SqlConnectionRequest(location, password=password, read_only=True),
            autocommit=True,
        ) as lease:
            with lease.cursor() as cursor:
                cursor.execute("SELECT 1")
                return int(cursor.fetchone()[0]) == 1
    except (OSError, RuntimeError, SqlInfrastructureError, ValueError):
        return False


def _login_exists(connection, login_name: str) -> bool:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT CASE WHEN SUSER_ID(?) IS NULL THEN 0 ELSE 1 END", login_name
        )
        return bool(cursor.fetchone()[0])
    finally:
        cursor.close()


def _database_exists(connection, database_name: str) -> bool:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT CASE WHEN DB_ID(?) IS NULL THEN 0 ELSE 1 END", database_name
        )
        return bool(cursor.fetchone()[0])
    finally:
        cursor.close()


def _database_marker(
    connection, database_name: str, property_name: str = DATABASE_MARKER_PROPERTY
) -> str:
    if not _database_exists(connection, database_name):
        return ""
    quoted = "[" + database_name.replace("]", "]]") + "]"
    cursor = connection.cursor()
    try:
        cursor.execute(
            f"SELECT CONVERT(nvarchar(128), value) FROM {quoted}.sys.extended_properties "
            "WHERE class=0 AND name=?",
            property_name,
        )
        row = cursor.fetchone()
        return str(row[0]) if row is not None else ""
    finally:
        cursor.close()


def _server_property(connection, property_name: str) -> str:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT CONVERT(nvarchar(4000), value) FROM sys.extended_properties "
            "WHERE class=0 AND name=?",
            property_name,
        )
        row = cursor.fetchone()
        return str(row[0]) if row is not None else ""
    finally:
        cursor.close()


def _set_server_property(connection, property_name: str, value: str) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "IF EXISTS (SELECT 1 FROM sys.extended_properties WHERE class=0 "
            "AND name=?) EXEC sys.sp_updateextendedproperty @name=?, @value=? "
            "ELSE EXEC sys.sp_addextendedproperty @name=?, @value=?",
            property_name,
            property_name,
            value,
            property_name,
            value,
        )
    finally:
        cursor.close()


def _require_server_marker(connection, expected_marker: str) -> None:
    actual = _server_property(connection, ENVIRONMENT_MARKER_PROPERTY)
    if not actual or not secrets.compare_digest(actual, expected_marker):
        raise RuntimeError("The SQL server ownership marker does not match.")


def _current_login_name(connection) -> str:
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT ORIGINAL_LOGIN()")
        return str(cursor.fetchone()[0])
    finally:
        cursor.close()


def _installer_principal() -> str:
    domain = os.environ.get("USERDOMAIN", "").strip()
    username = os.environ.get("USERNAME", "").strip()
    if not domain or not username:
        raise RuntimeError("The Windows setup identity is unavailable.")
    return f"{domain}\\{username}"


if __name__ == "__main__":
    raise SystemExit(main())
