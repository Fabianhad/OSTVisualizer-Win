from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import struct
import sys
import uuid
from dataclasses import replace
from datetime import date, datetime, time, timezone
from pathlib import Path

import pyodbc

from .common import (
    BACKUP_PROPERTY,
    DATABASE_PROPERTY,
    DEPLOYMENT_PROPERTY,
    DEPLOYMENT_KIND_PROPERTY,
    DISPOSABLE_PROPERTY,
    ConnectionSecret,
    DeploymentConfig,
    PRIVATE_STATE_ROOT,
    REPOSITORY_ROOT,
    active_application_sessions,
    atomic_write_private,
    connect,
    database_marker,
    load_config,
    quote_identifier,
    read_secret,
    redact_text,
    require_marker,
    require_private_file,
    scalar,
    server_marker,
    set_extended_property,
    verify_secret_matches,
    write_secret,
)

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ost_visualizer.domain.entities.database_descriptor import (  # noqa: E402
    DatabaseDescriptor,
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.sql.client_permissions import (  # noqa: E402
    SQL_CLIENT_DATABASE_ROLES,
    apply_sql_client_permissions,
    require_sql_client_editability,
)
from ost_visualizer.infrastructure.sql.connection_manager import SqlConnectionManager  # noqa: E402
from ost_visualizer.infrastructure.sql.database_creator import SqlDatabaseCreator  # noqa: E402
from ost_visualizer.infrastructure.database.descriptor_registry import DatabaseDescriptorRegistry  # noqa: E402
from ost_visualizer.infrastructure.sql.collaboration_store import SqlCollaborationStore  # noqa: E402
from ost_visualizer.infrastructure.sql.remote_change_reader import SqlRemoteChangeReader  # noqa: E402
from ost_visualizer.application.dtos.collaboration_dtos import PresenceMode, ResourceRef  # noqa: E402
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1  # noqa: E402
from ost_visualizer.infrastructure.sql.schema_inspector import SqlSchemaInspector  # noqa: E402
from ost_visualizer.infrastructure.sql.schema_validator import SqlSchemaValidator  # noqa: E402

APPLICATION_VERSION = "container-server"
CONTAINER_DEPLOYMENT_KIND = "container"
RESTORE_DATABASE_NAME = re.compile(
    r"\AOSTV_(?:RESTORE|MIGRATE)_[0-9]{8}_[0-9]{6}_[0-9a-f]{8}\Z", re.ASCII
)


def _secret_path(config: DeploymentConfig, role: str) -> Path:
    return config.secrets_directory / f"{role}.json"


def _password() -> str:
    # SQL Server accepts 128 characters; this includes all policy character groups.
    return "Ov!" + secrets.token_urlsafe(72)


def create_secrets(config: DeploymentConfig) -> dict[str, object]:
    marker_path = config.ownership_marker_file
    config.secrets_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(config.secrets_directory, 0o700)
    os.chmod(marker_path.parent, 0o700)
    if marker_path.exists():
        require_private_file(marker_path, label="ownership marker")
        marker = marker_path.read_text(encoding="utf-8").strip()
        uuid.UUID(marker)
    else:
        marker = str(uuid.uuid4())
        atomic_write_private(marker_path, marker + "\n")
    created: list[str] = []
    role_specs = [
        ("admin", config.admin_login, config.database),
        ("client", config.client_login, config.database),
    ]
    if not _secret_path(config, "admin").exists():
        role_specs.insert(0, ("bootstrap", "sa", "master"))
    for role, username, database in role_specs:
        path = _secret_path(config, role)
        if path.exists():
            existing = read_secret(path)
            if existing.ownership_marker != marker:
                raise RuntimeError(f"The existing {role} secret has a different ownership marker.")
            continue
        write_secret(
            path,
            ConnectionSecret(
                server=config.server,
                port=config.port,
                database=database,
                username=username,
                password=_password(),
                encrypt=True,
                trust_server_certificate=False,
                ownership_marker=marker,
            ),
        )
        created.append(role)
    return {"status": "ready", "created_credentials": created, "secrets_printed": False}


def create_recovery_bootstrap(config: DeploymentConfig) -> dict[str, object]:
    """Create a one-use sa secret while preserving the deployment marker."""
    create_secrets(config)
    path = _secret_path(config, "bootstrap")
    admin = read_secret(_secret_path(config, "admin"))
    verify_secret_matches(admin, config, role="admin")
    if path.exists():
        bootstrap = read_secret(path)
        if (
            bootstrap.username != "sa"
            or bootstrap.database != "master"
            or bootstrap.ownership_marker != admin.ownership_marker
        ):
            raise RuntimeError("The recovery bootstrap credential is invalid.")
    else:
        write_secret(
            path,
            ConnectionSecret(
                server=config.server,
                port=config.port,
                database="master",
                username="sa",
                password=_password(),
                encrypt=True,
                trust_server_certificate=False,
                ownership_marker=admin.ownership_marker,
            ),
        )
    return {"status": "recovery-bootstrap-ready", "secrets_printed": False}


def bootstrap_admin(config: DeploymentConfig) -> dict[str, object]:
    bootstrap_path = _secret_path(config, "bootstrap")
    bootstrap = read_secret(bootstrap_path)
    admin = read_secret(_secret_path(config, "admin"))
    if bootstrap.username != "sa" or bootstrap.database != "master":
        raise RuntimeError("The bootstrap credential is invalid.")
    verify_secret_matches(admin, config, role="admin")
    require_marker(bootstrap.ownership_marker, admin.ownership_marker, "credential")
    with connect(bootstrap, database="master", app="OSTV SQL Bootstrap") as connection:
        existing_marker = server_marker(connection)
        if existing_marker:
            require_marker(existing_marker, admin.ownership_marker, "server")
        cursor = connection.cursor()
        try:
            cursor.execute(
                "DECLARE @secret nvarchar(128)=?; DECLARE @sql nvarchar(max); "
                "IF SUSER_ID(?) IS NULL BEGIN "
                "SET @sql=N'CREATE LOGIN ' + QUOTENAME(?) + N' WITH PASSWORD=' + "
                "QUOTENAME(@secret, NCHAR(39)) + N', CHECK_POLICY=ON, "
                "CHECK_EXPIRATION=OFF, DEFAULT_DATABASE=[master]'; EXEC(@sql); END "
                "ELSE BEGIN SET @sql=N'ALTER LOGIN ' + QUOTENAME(?) + N' WITH PASSWORD=' + "
                "QUOTENAME(@secret, NCHAR(39)); EXEC(@sql); END; "
                "SET @sql=N'ALTER SERVER ROLE [sysadmin] ADD MEMBER ' + QUOTENAME(?); EXEC(@sql); "
                "SET @sql=N'ALTER LOGIN ' + QUOTENAME(?) + N' ENABLE'; EXEC(@sql);",
                admin.password,
                config.admin_login,
                config.admin_login,
                config.admin_login,
                config.admin_login,
                config.admin_login,
            )
            set_extended_property(cursor, DEPLOYMENT_PROPERTY, admin.ownership_marker)
            set_extended_property(
                cursor,
                DEPLOYMENT_KIND_PROPERTY,
                f"{CONTAINER_DEPLOYMENT_KIND}:{config.container_name}",
            )
            set_extended_property(cursor, BACKUP_PROPERTY, str(config.backup_sql_directory))
        finally:
            cursor.close()
    with connect(replace(admin, database="master"), database="master", app="OSTV SQL Admin Verification") as connection:
        _require_owned_server(connection, admin, config)
        if int(scalar(connection, "SELECT IS_SRVROLEMEMBER(N'sysadmin')") or 0) != 1:
            raise RuntimeError("The dedicated administrator did not receive sysadmin.")
        cursor = connection.cursor()
        try:
            cursor.execute("ALTER LOGIN [sa] DISABLE")
        finally:
            cursor.close()
    bootstrap_path.unlink()
    return {"status": "administrator-configured", "sa_disabled": True, "administrator_verified": True}


def provision_database(config: DeploymentConfig) -> dict[str, object]:
    admin = read_secret(_secret_path(config, "admin"))
    client = read_secret(_secret_path(config, "client"))
    verify_secret_matches(admin, config, role="admin")
    verify_secret_matches(client, config, role="client")
    require_marker(admin.ownership_marker, client.ownership_marker, "credential")
    admin_master = replace(admin, database="master")
    database_exists = False
    client_login_existed = False
    with connect(admin_master, database="master") as connection:
        _require_owned_server(connection, admin, config)
        database_exists = bool(
            scalar(
                connection,
                "SELECT CASE WHEN DB_ID(?) IS NULL THEN 0 ELSE 1 END",
                config.database,
            )
        )
        client_login_existed = bool(
            scalar(
                connection,
                "SELECT CASE WHEN SUSER_ID(?) IS NULL THEN 0 ELSE 1 END",
                config.client_login,
            )
        )
        if database_exists:
            with connect(admin, database=config.database) as database_connection:
                existing_marker = database_marker(database_connection)
                if not existing_marker:
                    quarantine = _backup(config, connection, config.database, prefix="unowned-mismatch")
                    raise RuntimeError(
                        "The configured database already exists without the OST Visualizer ownership marker. "
                        f"A copy-only backup was created at {quarantine}; the database was not modified."
                    )
                require_marker(existing_marker, admin.ownership_marker, "database")
    disposable_marker = f"provision-{uuid.uuid4()}"
    created = False
    marked = False
    verification: dict[str, object] | None = None
    operation_error: Exception | None = None
    try:
        if not database_exists:
            creator = SqlDatabaseCreator(SqlConnectionManager())
            try:
                creator.create_database(
                    _location(admin, "master"),
                    config.database,
                    admin.password,
                    application_version=APPLICATION_VERSION,
                    actor=config.admin_login,
                )
            finally:
                with connect(admin_master, database="master") as connection:
                    _require_owned_server(connection, admin, config)
                    created = scalar(connection, "SELECT DB_ID(?)", config.database) is not None
        with connect(admin, database=config.database) as connection:
            cursor = connection.cursor()
            try:
                if created:
                    set_extended_property(cursor, DISPOSABLE_PROPERTY, disposable_marker)
                    marked = True
                set_extended_property(cursor, DATABASE_PROPERTY, admin.ownership_marker)
            finally:
                cursor.close()
        _configure_client(config, admin_master, admin, client, rotate=False)
        verification = validate_environment(config, run_backup=False)
        if created:
            with connect(admin, database=config.database) as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute(
                        "IF EXISTS (SELECT 1 FROM sys.extended_properties WHERE class=0 AND name=?) "
                        "EXEC sys.sp_dropextendedproperty @name=?",
                        DISPOSABLE_PROPERTY,
                        DISPOSABLE_PROPERTY,
                    )
                finally:
                    cursor.close()
            created = False
    except Exception as exc:
        operation_error = exc
    cleanup_errors: list[Exception] = []
    if created:
        try:
            _drop_created_database(
                config,
                admin,
                config.database,
                disposable_marker=disposable_marker if marked else None,
                allow_configured_name=True,
            )
        except Exception as exc:
            cleanup_errors.append(exc)
    if operation_error is not None and not client_login_existed:
        try:
            _drop_created_client_login(config, admin)
        except Exception as exc:
            cleanup_errors.append(exc)
    _raise_after_cleanup("Database provisioning", operation_error, tuple(cleanup_errors))
    if verification is None:
        raise RuntimeError("Database provisioning ended without canonical validation.")
    return {
        "status": "configured",
        "database_created": not database_exists,
        "schema_version": verification["schema_version"],
        "schema_checksum": verification["schema_checksum"],
        "client_verified": verification["client_editability"],
    }


def _configure_client(
    config: DeploymentConfig,
    admin_master: ConnectionSecret,
    admin: ConnectionSecret,
    client: ConnectionSecret,
    *,
    rotate: bool,
) -> None:
    with connect(admin_master, database="master") as connection:
        _require_owned_server(connection, admin, config)
        login_exists = bool(
            scalar(
                connection,
                "SELECT CASE WHEN SUSER_ID(?) IS NULL THEN 0 ELSE 1 END",
                config.client_login,
            )
        )
        if login_exists and not rotate:
            try:
                with connect(client, database=config.database, app="OSTV Client Credential Verification"):
                    pass
            except pyodbc.Error as exc:
                raise RuntimeError("The stored client credential no longer authenticates; run rotate_client_password.sh.") from exc
        if rotate or not login_exists:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "DECLARE @secret nvarchar(128)=?; DECLARE @sql nvarchar(max); "
                    "IF SUSER_ID(?) IS NULL SET @sql=N'CREATE LOGIN ' + QUOTENAME(?) + "
                    "N' WITH PASSWORD=' + QUOTENAME(@secret, NCHAR(39)) + "
                    "N', CHECK_POLICY=ON, CHECK_EXPIRATION=OFF, DEFAULT_DATABASE=' + QUOTENAME(?) "
                    "ELSE SET @sql=N'ALTER LOGIN ' + QUOTENAME(?) + N' WITH PASSWORD=' + "
                    "QUOTENAME(@secret, NCHAR(39)); EXEC(@sql); "
                    "SET @sql=N'ALTER LOGIN ' + QUOTENAME(?) + N' ENABLE'; EXEC(@sql);",
                    client.password,
                    config.client_login,
                    config.client_login,
                    config.database,
                    config.client_login,
                    config.client_login,
                )
            finally:
                cursor.close()
    with connect(admin, database=config.database) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(
                "IF USER_ID(?) IS NULL BEGIN DECLARE @sql nvarchar(max)=N'CREATE USER ' + "
                "QUOTENAME(?) + N' FOR LOGIN ' + QUOTENAME(?) + N' WITH DEFAULT_SCHEMA=[dbo]'; EXEC(@sql); END "
                "ELSE BEGIN DECLARE @remap nvarchar(max)=N'ALTER USER ' + QUOTENAME(?) + "
                "N' WITH LOGIN = ' + QUOTENAME(?); EXEC(@remap); END",
                config.client_login,
                config.client_login,
                config.client_login,
                config.client_login,
                config.client_login,
            )
            apply_sql_client_permissions(cursor, config.client_login)
        finally:
            cursor.close()
    with connect(client, database=config.database, app="OST Visualizer Permission Verification") as connection:
        cursor = connection.cursor()
        try:
            require_sql_client_editability(cursor)
        finally:
            cursor.close()


def validate_environment(
    config: DeploymentConfig, *, run_backup: bool = False
) -> dict[str, object]:
    admin = read_secret(_secret_path(config, "admin"))
    client = read_secret(_secret_path(config, "client"))
    verify_secret_matches(admin, config, role="admin")
    verify_secret_matches(client, config, role="client")
    require_marker(admin.ownership_marker, client.ownership_marker, "credential")
    with connect(replace(admin, database="master"), database="master", app="OSTV SQL Validator") as connection:
        _require_owned_server(connection, admin, config)
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT CONVERT(nvarchar(128), SERVERPROPERTY('ProductVersion')), "
                "CONVERT(nvarchar(128), SERVERPROPERTY('Edition')), "
                "CONVERT(int, SERVERPROPERTY('ProductMajorVersion')), "
                "CASE WHEN IS_SRVROLEMEMBER(N'sysadmin')=1 THEN 1 ELSE 0 END, "
                "c.encrypt_option, c.auth_scheme FROM sys.dm_exec_connections c "
                "WHERE c.session_id=@@SPID"
            )
            server_row = cursor.fetchone()
        finally:
            cursor.close()
    if int(server_row[2]) != 17:
        raise RuntimeError("This deployment requires supported SQL Server 2025 (major version 17).")
    if int(server_row[3]) != 1:
        raise RuntimeError("Dedicated administrator access is not available.")
    if not str(server_row[1]).casefold().startswith(config.edition.casefold()):
        raise RuntimeError("The installed SQL Server edition does not match the private configuration.")
    with connect(admin, database=config.database, app="OSTV SQL Schema Validator") as connection:
        require_marker(database_marker(connection), admin.ownership_marker, "database")
    inventory = SqlSchemaInspector().inspect(_location(admin, config.database), admin.password)
    report = SqlSchemaValidator(SQL_SCHEMA_V1.core_schema).validate(inventory)
    if not report.is_valid:
        raise RuntimeError("Canonical schema validation failed: " + report.user_message)
    with connect(client, database=config.database, app="OST Visualizer Client Validator") as connection:
        cursor = connection.cursor()
        try:
            require_sql_client_editability(cursor)
            permissions = _permission_inventory(cursor)
            cursor.execute(
                "SELECT CHANGE_TRACKING_CURRENT_VERSION(), "
                "CHANGE_TRACKING_MIN_VALID_VERSION(OBJECT_ID(N'ostv.ChangeTransactions'))"
            )
            feed_row = cursor.fetchone()
        finally:
            cursor.close()
    if str(server_row[4]).casefold() != "true":
        raise RuntimeError("The validated client connection is not encrypted.")
    _validate_permission_inventory(permissions)
    if feed_row[0] is None or feed_row[1] is None:
        raise RuntimeError("Change Tracking collaboration feed versions are unavailable.")
    backup_result: dict[str, object] = {"performed": False}
    if run_backup:
        backup_path = backup_database(config)
        restore_result = restore_verify(config, backup_path)
        backup_result = {"performed": True, "path": str(backup_path), **restore_result}
    return {
        "status": "valid",
        "server_version": str(server_row[0]),
        "edition": str(server_row[1]),
        "schema_version": inventory.schema_version,
        "schema_checksum": inventory.schema_checksum,
        "canonical_checksum": SQL_SCHEMA_V1.checksum,
        "schema_valid": True,
        "snapshot_isolation": inventory.snapshot_isolation_enabled,
        "change_tracking": inventory.change_tracking_enabled,
        "change_tracking_retention_days": inventory.change_tracking_retention_days,
        "change_tracking_auto_cleanup": inventory.change_tracking_auto_cleanup,
        "tracked_tables": [f"{s}.{t}" for s, t in sorted(inventory.change_tracking_tables)],
        "client_editability": True,
        "client_server_roles": permissions["server_roles"],
        "client_database_roles": permissions["database_roles"],
        "connection_encrypted": True,
        "certificate_validated": True,
        "feed_current_version": int(feed_row[0]),
        "feed_min_valid_version": int(feed_row[1]),
        "backup_restore": backup_result,
    }


def _permission_inventory(cursor) -> dict[str, object]:
    cursor.execute(
        "SELECT r.name FROM sys.server_role_members rm JOIN sys.server_principals r "
        "ON r.principal_id=rm.role_principal_id JOIN sys.server_principals m "
        "ON m.principal_id=rm.member_principal_id WHERE m.name=ORIGINAL_LOGIN() ORDER BY r.name"
    )
    server_roles = [str(row[0]) for row in cursor.fetchall()]
    cursor.execute(
        "SELECT r.name FROM sys.database_role_members rm JOIN sys.database_principals r "
        "ON r.principal_id=rm.role_principal_id JOIN sys.database_principals m "
        "ON m.principal_id=rm.member_principal_id WHERE m.name=USER_NAME() ORDER BY r.name"
    )
    database_roles = [str(row[0]) for row in cursor.fetchall()]
    cursor.execute(
        "SELECT COALESCE(HAS_PERMS_BY_NAME(DB_NAME(), N'DATABASE', N'ALTER'),0), "
        "COALESCE(HAS_PERMS_BY_NAME(DB_NAME(), N'DATABASE', N'CONTROL'),0), "
        "COALESCE(HAS_PERMS_BY_NAME(NULL,NULL,N'CREATE ANY DATABASE'),0), "
        "COALESCE(HAS_PERMS_BY_NAME(NULL,NULL,N'ALTER ANY LOGIN'),0)"
    )
    elevated = tuple(int(value) for value in cursor.fetchone())
    return {"server_roles": server_roles, "database_roles": database_roles, "elevated": elevated}


def _validate_permission_inventory(value: dict[str, object]) -> None:
    forbidden_server = {"sysadmin", "dbcreator", "securityadmin", "serveradmin"}
    forbidden_database = {"db_owner", "db_ddladmin", "db_securityadmin"}
    if forbidden_server.intersection(value["server_roles"]):
        raise RuntimeError("The application login has a forbidden server role.")
    if forbidden_database.intersection(value["database_roles"]):
        raise RuntimeError("The application login has a forbidden database role.")
    if set(value["database_roles"]) != set(SQL_CLIENT_DATABASE_ROLES):
        raise RuntimeError("The application database-role membership is not canonical.")
    if tuple(value["elevated"]) != (0, 0, 0, 0):
        raise RuntimeError("The application login has forbidden elevated permissions.")


def _require_owned_server(
    connection: pyodbc.Connection,
    secret: ConnectionSecret,
    config: DeploymentConfig,
) -> None:
    require_marker(server_marker(connection), secret.ownership_marker, "server")
    actual_kind = str(
        scalar(
            connection,
            "SELECT CONVERT(nvarchar(256), value) FROM sys.extended_properties "
            "WHERE class=0 AND name=?",
            DEPLOYMENT_KIND_PROPERTY,
        )
        or ""
    )
    expected_kind = f"{CONTAINER_DEPLOYMENT_KIND}:{config.container_name}"
    if actual_kind != expected_kind:
        raise RuntimeError("Refusing operation because the SQL container ownership identity does not match.")


def repair_permissions(config: DeploymentConfig) -> dict[str, object]:
    admin = read_secret(_secret_path(config, "admin"))
    client = read_secret(_secret_path(config, "client"))
    with connect(replace(admin, database="master"), database="master") as connection:
        _require_owned_server(connection, admin, config)
    with connect(admin, database=config.database) as connection:
        require_marker(database_marker(connection), admin.ownership_marker, "database")
    _configure_client(config, replace(admin, database="master"), admin, client, rotate=False)
    validate_environment(config, run_backup=False)
    return {"status": "permissions-repaired", "client_verified": True}


def rotate_client_password(config: DeploymentConfig) -> dict[str, object]:
    admin = read_secret(_secret_path(config, "admin"))
    old = read_secret(_secret_path(config, "client"))
    replacement = replace(old, password=_password())
    temporary = config.secrets_directory / "client.next.json"
    write_secret(temporary, replacement)
    try:
        _configure_client(
            config,
            replace(admin, database="master"),
            admin,
            replacement,
            rotate=True,
        )
        client_path = _secret_path(config, "client")
        os.replace(temporary, client_path)
        os.chmod(client_path, 0o600)
    except Exception as rotation_error:
        temporary.unlink(missing_ok=True)
        try:
            _configure_client(
                config,
                replace(admin, database="master"),
                admin,
                old,
                rotate=True,
            )
        except Exception as rollback_error:
            raise ExceptionGroup(
                "Client password rotation and rollback both failed; administrator recovery is required.",
                (rotation_error, rollback_error),
            )
        raise
    return {"status": "client-password-rotated", "client_verified": True, "secret_printed": False}


def backup_database(config: DeploymentConfig) -> Path:
    admin = read_secret(_secret_path(config, "admin"))
    with connect(replace(admin, database="master"), database="master", app="OSTV SQL Backup") as connection:
        _require_owned_server(connection, admin, config)
        with connect(admin, database=config.database, app="OSTV SQL Backup Ownership") as database_connection:
            require_marker(database_marker(database_connection), admin.ownership_marker, "database")
        return _backup(config, connection, config.database, prefix="full")


def _backup(
    config: DeploymentConfig,
    connection: pyodbc.Connection,
    database_name: str,
    *,
    prefix: str,
) -> Path:
    config.backup_host_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = config.backup_host_directory / f"{database_name}_{prefix}_{timestamp}.bak"
    sql_path = config.backup_sql_directory / path.name
    quoted = quote_identifier(database_name)
    connection.timeout = 600
    cursor = connection.cursor()
    try:
        cursor.execute(
            f"DECLARE @path nvarchar(4000)=?; BACKUP DATABASE {quoted} TO DISK=@path "
            "WITH COPY_ONLY, CHECKSUM, INIT, STATS=10; "
            "RESTORE VERIFYONLY FROM DISK=@path WITH CHECKSUM;",
            str(sql_path),
        )
        _drain_results(cursor)
    finally:
        cursor.close()
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("SQL Server did not create the expected backup file.")
    os.chmod(path, 0o600)
    return path


def restore_verify(config: DeploymentConfig, path: Path) -> dict[str, object]:
    _, sql_path = _resolve_backup_path(config, path)
    admin = read_secret(_secret_path(config, "admin"))
    marker = f"restore-{uuid.uuid4()}"
    target = "OSTV_RESTORE_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + secrets.token_hex(4)
    quote_identifier(target)
    data_path = config.data_sql_directory / f"{target}.mdf"
    log_path = config.data_sql_directory / f"{target}_log.ldf"
    admin_master = replace(admin, database="master")
    target_secret = replace(admin, database=target)
    created = False
    marked = False
    result: dict[str, object] | None = None
    operation_error: Exception | None = None
    try:
        with connect(admin_master, database="master", app="OSTV SQL Restore Verification") as connection:
            _require_owned_server(connection, admin, config)
            if scalar(connection, "SELECT DB_ID(?)", target) is not None:
                raise RuntimeError("The unique restore-validation database already exists.")
            try:
                _restore_database_files(connection, sql_path, target, data_path, log_path)
            finally:
                created = scalar(connection, "SELECT DB_ID(?)", target) is not None
        with connect(target_secret, database=target, app="OSTV SQL Restore Ownership") as connection:
            cursor = connection.cursor()
            try:
                set_extended_property(cursor, DISPOSABLE_PROPERTY, marker)
                marked = True
            finally:
                cursor.close()
            require_marker(database_marker(connection), admin.ownership_marker, "restored database")
        inventory = SqlSchemaInspector().inspect(_location(admin, target), admin.password)
        report = SqlSchemaValidator(SQL_SCHEMA_V1.core_schema).validate(inventory)
        if not report.is_valid:
            raise RuntimeError("The restored validation database is not canonical: " + report.user_message)
        result = {
            "restore_verified": True,
            "restore_schema_valid": True,
            "restore_target_removed": True,
        }
    except Exception as exc:
        operation_error = exc
    cleanup_error: Exception | None = None
    try:
        if created:
            _drop_created_database(
                config,
                admin,
                target,
                disposable_marker=marker if marked else None,
            )
    except Exception as exc:
        cleanup_error = exc
    _raise_after_cleanup(
        "Restore verification",
        operation_error,
        () if cleanup_error is None else (cleanup_error,),
    )
    if result is None:
        raise RuntimeError("Restore verification ended without a result.")
    return result


def _resolve_backup_path(config: DeploymentConfig, path: Path) -> tuple[Path, Path]:
    path = path.resolve()
    backup_root = config.backup_host_directory.resolve()
    if backup_root not in path.parents or not path.is_file() or path.suffix.casefold() != ".bak":
        raise RuntimeError("The restore source is outside the owned backup directory.")
    return path, config.backup_sql_directory / path.relative_to(backup_root)


def _restore_database_files(
    connection: pyodbc.Connection,
    sql_path: Path,
    target: str,
    data_path: Path,
    log_path: Path,
) -> None:
    connection.timeout = 600
    cursor = connection.cursor()
    try:
        cursor.execute(
            "DECLARE @path nvarchar(4000)=?; RESTORE VERIFYONLY FROM DISK=@path WITH CHECKSUM",
            str(sql_path),
        )
        cursor.execute("DECLARE @path nvarchar(4000)=?; RESTORE FILELISTONLY FROM DISK=@path", str(sql_path))
        rows = cursor.fetchall()
        data_rows = [row for row in rows if str(row[2]).upper() == "D"]
        log_rows = [row for row in rows if str(row[2]).upper() == "L"]
        if len(data_rows) != 1 or len(log_rows) != 1:
            raise RuntimeError("Restore expects exactly one data and one log file.")
        cursor.execute(
            f"DECLARE @path nvarchar(4000)=?, @data sysname=?, @log sysname=?, "
            f"@dataPath nvarchar(4000)=?, @logPath nvarchar(4000)=?; "
            f"DECLARE @sql nvarchar(max)=N'RESTORE DATABASE {quote_identifier(target)} FROM DISK=' + "
            "QUOTENAME(@path,NCHAR(39)) + N' WITH CHECKSUM, RECOVERY, MOVE ' + "
            "QUOTENAME(@data,NCHAR(39)) + N' TO ' + QUOTENAME(@dataPath,NCHAR(39)) + "
            "N', MOVE ' + QUOTENAME(@log,NCHAR(39)) + N' TO ' + QUOTENAME(@logPath,NCHAR(39)); EXEC(@sql);",
            str(sql_path), str(data_rows[0][0]), str(log_rows[0][0]), str(data_path), str(log_path),
        )
        _drain_results(cursor)
    finally:
        cursor.close()


def _drop_created_database(
    config: DeploymentConfig,
    admin: ConnectionSecret,
    target: str,
    *,
    disposable_marker: str | None,
    allow_configured_name: bool = False,
) -> None:
    unmarked_name_is_safe = RESTORE_DATABASE_NAME.fullmatch(target) or (
        allow_configured_name and target == config.database
    )
    if disposable_marker is None and not unmarked_name_is_safe:
        raise RuntimeError("Refusing unmarked cleanup for a non-temporary database name.")
    admin_master = replace(admin, database="master")
    with connect(admin_master, database="master", app="OSTV SQL Deterministic Cleanup") as connection:
        _require_owned_server(connection, admin, config)
        if scalar(connection, "SELECT DB_ID(?)", target) is None:
            return
        if active_application_sessions(connection, target):
            raise RuntimeError("Refusing cleanup while OST Visualizer sessions are active.")
        if disposable_marker is not None:
            target_secret = replace(admin, database=target)
            with connect(target_secret, database=target) as target_connection:
                value = scalar(
                    target_connection,
                    "SELECT CONVERT(nvarchar(128), value) FROM sys.extended_properties "
                    "WHERE class=0 AND name=?",
                    DISPOSABLE_PROPERTY,
                )
                require_marker(str(value or ""), disposable_marker, "temporary database")
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"ALTER DATABASE {quote_identifier(target)} SET SINGLE_USER "
                f"WITH ROLLBACK IMMEDIATE; DROP DATABASE {quote_identifier(target)}"
            )
        finally:
            cursor.close()


def _drop_created_client_login(
    config: DeploymentConfig, admin: ConnectionSecret
) -> None:
    admin_master = replace(admin, database="master")
    with connect(admin_master, database="master", app="OSTV SQL Provisioning Cleanup") as connection:
        _require_owned_server(connection, admin, config)
        if scalar(connection, "SELECT SUSER_ID(?)", config.client_login) is None:
            return
        cursor = connection.cursor()
        try:
            cursor.execute(
                "DECLARE @sql nvarchar(max)=N'DROP LOGIN ' + QUOTENAME(?); EXEC(@sql);",
                config.client_login,
            )
        finally:
            cursor.close()


def _raise_after_cleanup(
    operation: str,
    operation_error: Exception | None,
    cleanup_errors: tuple[Exception, ...],
) -> None:
    if operation_error is not None and cleanup_errors:
        raise ExceptionGroup(
            f"{operation} and deterministic cleanup both failed.",
            (operation_error, *cleanup_errors),
        )
    if cleanup_errors:
        raise ExceptionGroup(f"{operation} cleanup failed.", cleanup_errors)
    if operation_error is not None:
        raise operation_error


def database_fingerprint(config: DeploymentConfig) -> dict[str, object]:
    admin = read_secret(_secret_path(config, "admin"))
    with connect(admin, database=config.database, app="OSTV Data Fingerprint") as connection:
        require_marker(database_marker(connection), admin.ownership_marker, "database")
        return _fingerprint_connection(config.database, connection)


def _fingerprint_connection(
    database_name: str, connection: pyodbc.Connection
) -> dict[str, object]:
    definitions: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = []
    for table in SQL_SCHEMA_V1.core_schema.tables:
        definitions.append(
            (
                "dbo",
                table.name,
                tuple(column.name for column in table.columns),
                tuple(column.name for column in table.columns if column.primary_key),
            )
        )
    definitions.extend(
        (table.schema, table.name, tuple(column.name for column in table.columns), table.primary_key)
        for table in SQL_SCHEMA_V1.tables
    )
    tables: dict[str, dict[str, object]] = {}
    for schema, table, columns, primary_key in sorted(definitions):
        column_sql = ",".join(quote_identifier(column) for column in columns)
        order_columns = primary_key or columns
        order_sql = ",".join(quote_identifier(column) for column in order_columns)
        cursor = connection.cursor()
        digest = hashlib.sha256()
        count = 0
        try:
            cursor.execute(
                f"SELECT {column_sql} FROM {quote_identifier(schema)}.{quote_identifier(table)} "
                f"ORDER BY {order_sql}"
            )
            while True:
                rows = cursor.fetchmany(512)
                if not rows:
                    break
                for row in rows:
                    count += 1
                    for value in row:
                        encoded = _fingerprint_value(value)
                        digest.update(len(encoded).to_bytes(8, "big"))
                        digest.update(encoded)
        finally:
            cursor.close()
        tables[f"{schema}.{table}"] = {"rows": count, "sha256": digest.hexdigest()}
    canonical = json.dumps(tables, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "database": database_name,
        "schema_checksum": SQL_SCHEMA_V1.checksum,
        "database_sha256": hashlib.sha256(canonical).hexdigest(),
        "tables": tables,
    }


def _fingerprint_value(value: object) -> bytes:
    if value is None:
        return b"N"
    if isinstance(value, bytes):
        return b"B" + value
    if isinstance(value, float):
        return b"F" + struct.pack(">d", value)
    if isinstance(value, bool):
        return b"T1" if value else b"T0"
    if isinstance(value, (date, datetime, time)):
        return b"D" + value.isoformat().encode("utf-8")
    return b"S" + str(value).encode("utf-8")


def restore_migration(
    config: DeploymentConfig,
    path: Path,
    source_marker_path: Path,
    expected_fingerprint_path: Path,
) -> dict[str, object]:
    expected_opt_in = f"restore-migration-{config.database}"
    if os.environ.get("OSTV_CONFIRM_DESTRUCTIVE") != expected_opt_in:
        raise RuntimeError(f"Set OSTV_CONFIRM_DESTRUCTIVE={expected_opt_in} for migration restore.")
    _, sql_path = _resolve_backup_path(config, path)
    for private_file in (source_marker_path, expected_fingerprint_path):
        require_private_file(private_file, label="migration validation file")
    source_marker = source_marker_path.read_text(encoding="utf-8").strip()
    uuid.UUID(source_marker)
    try:
        expected_fingerprint = json.loads(expected_fingerprint_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("The expected migration fingerprint is unreadable.") from exc
    admin = read_secret(_secret_path(config, "admin"))
    admin_master = replace(admin, database="master")
    staging = "OSTV_MIGRATE_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + secrets.token_hex(4)
    quote_identifier(staging)
    disposable_marker = f"migration-{uuid.uuid4()}"
    current_name = staging
    created = False
    marked = False
    operation_error: Exception | None = None
    actual_fingerprint: dict[str, object] | None = None
    validation: dict[str, object] | None = None
    client_login_existed = False
    try:
        with connect(admin_master, database="master", app="OSTV Container Migration") as connection:
            _require_owned_server(connection, admin, config)
            if scalar(connection, "SELECT DB_ID(?)", config.database) is not None:
                raise RuntimeError("The migration target database already exists; refusing overwrite.")
            if scalar(connection, "SELECT DB_ID(?)", staging) is not None:
                raise RuntimeError("The unique migration staging database already exists.")
            client_login_existed = scalar(
                connection,
                "SELECT SUSER_ID(?)",
                config.client_login,
            ) is not None
            try:
                _restore_database_files(
                    connection,
                    sql_path,
                    staging,
                    config.data_sql_directory / f"{staging}.mdf",
                    config.data_sql_directory / f"{staging}_log.ldf",
                )
            finally:
                created = scalar(connection, "SELECT DB_ID(?)", staging) is not None
        staged = replace(admin, database=staging)
        with connect(staged, database=staging, app="OSTV Migration Validation") as connection:
            cursor = connection.cursor()
            try:
                set_extended_property(cursor, DISPOSABLE_PROPERTY, disposable_marker)
                marked = True
            finally:
                cursor.close()
            require_marker(database_marker(connection), source_marker, "source database")
            inventory = SqlSchemaInspector().inspect(_location(admin, staging), admin.password)
            report = SqlSchemaValidator(SQL_SCHEMA_V1.core_schema).validate(inventory)
            if not report.is_valid:
                raise RuntimeError("The migration backup is not canonical: " + report.user_message)
            actual_fingerprint = _fingerprint_connection(config.database, connection)
            if actual_fingerprint != expected_fingerprint:
                raise RuntimeError("The restored database fingerprint does not match the native source.")
            cursor = connection.cursor()
            try:
                set_extended_property(cursor, DATABASE_PROPERTY, admin.ownership_marker)
            finally:
                cursor.close()
        with connect(admin_master, database="master", app="OSTV Migration Adoption") as connection:
            _require_owned_server(connection, admin, config)
            if scalar(connection, "SELECT DB_ID(?)", config.database) is not None:
                raise RuntimeError("The migration target appeared during validation; refusing overwrite.")
            cursor = connection.cursor()
            try:
                cursor.execute(
                    f"ALTER DATABASE {quote_identifier(staging)} MODIFY NAME = "
                    f"{quote_identifier(config.database)}"
                )
            finally:
                cursor.close()
            current_name = config.database
            cursor = connection.cursor()
            try:
                cursor.execute(
                    f"ALTER AUTHORIZATION ON DATABASE::{quote_identifier(config.database)} "
                    f"TO {quote_identifier(config.admin_login)}"
                )
            finally:
                cursor.close()
        restored = replace(admin, database=config.database)
        _configure_client(
            config,
            admin_master,
            restored,
            read_secret(_secret_path(config, "client")),
            rotate=True,
        )
        validation = validate_environment(config, run_backup=False)
        with connect(restored, database=config.database, app="OSTV Migration Finalization") as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "IF EXISTS (SELECT 1 FROM sys.extended_properties WHERE class=0 AND name=?) "
                    "EXEC sys.sp_dropextendedproperty @name=?",
                    DISPOSABLE_PROPERTY,
                    DISPOSABLE_PROPERTY,
                )
            finally:
                cursor.close()
        created = False
    except Exception as exc:
        operation_error = exc
    cleanup_error: Exception | None = None
    if created:
        try:
            _drop_created_database(
                config,
                admin,
                current_name,
                disposable_marker=disposable_marker if marked else None,
            )
        except Exception as exc:
            cleanup_error = exc
    login_cleanup_error: Exception | None = None
    if operation_error is not None and not client_login_existed:
        try:
            _drop_created_client_login(config, admin)
        except Exception as exc:
            login_cleanup_error = exc
    cleanup_errors = tuple(
        error for error in (cleanup_error, login_cleanup_error) if error is not None
    )
    _raise_after_cleanup("Migration", operation_error, cleanup_errors)
    if actual_fingerprint is None:
        raise RuntimeError("Migration ended without a validated fingerprint.")
    if validation is None:
        raise RuntimeError("Migration ended without canonical validation.")
    return {
        "status": "migration-restored",
        "schema_valid": validation["schema_valid"],
        "data_fingerprint_match": True,
        "database_sha256": actual_fingerprint["database_sha256"],
    }


def uninstall_database(config: DeploymentConfig) -> dict[str, object]:
    expected = f"uninstall-{config.database}"
    if os.environ.get("OSTV_CONFIRM_DESTRUCTIVE") != expected:
        raise RuntimeError(f"Set OSTV_CONFIRM_DESTRUCTIVE={expected} for owned SQL resource removal.")
    admin = read_secret(_secret_path(config, "admin"))
    admin_master = replace(admin, database="master")
    with connect(admin_master, database="master", app="OSTV SQL Uninstall") as connection:
        _require_owned_server(connection, admin, config)
        if active_application_sessions(connection, config.database):
            raise RuntimeError("Refusing uninstall while OST Visualizer sessions are active.")
        with connect(admin, database=config.database) as database_connection:
            require_marker(database_marker(database_connection), admin.ownership_marker, "database")
        backup = _backup(config, connection, config.database, prefix="pre-uninstall")
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"ALTER DATABASE {quote_identifier(config.database)} SET SINGLE_USER "
                f"WITH ROLLBACK IMMEDIATE; DROP DATABASE {quote_identifier(config.database)}"
            )
            cursor.execute(
                "DECLARE @sql nvarchar(max); IF SUSER_ID(?) IS NOT NULL BEGIN "
                "SET @sql=N'DROP LOGIN ' + QUOTENAME(?); EXEC(@sql); END",
                config.client_login,
                config.client_login,
            )
        finally:
            cursor.close()
    return {"status": "owned-database-removed", "recovery_backup": str(backup), "sql_package_removed": False}


def cleanup_restore_databases(config: DeploymentConfig) -> dict[str, object]:
    if os.environ.get("OSTV_CONFIRM_DESTRUCTIVE") != "cleanup-restore-validation":
        raise RuntimeError(
            "Set OSTV_CONFIRM_DESTRUCTIVE=cleanup-restore-validation to remove owned restore-validation databases."
        )
    admin = read_secret(_secret_path(config, "admin"))
    admin_master = replace(admin, database="master")
    removed: list[str] = []
    with connect(admin_master, database="master", app="OSTV SQL Restore Recovery") as connection:
        _require_owned_server(connection, admin, config)
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT name FROM sys.databases WHERE name LIKE N'OSTV[_]RESTORE[_]%'")
            names = [str(row[0]) for row in cursor.fetchall()]
        finally:
            cursor.close()
        for name in names:
            if not name.startswith("OSTV_RESTORE_") or not RESTORE_DATABASE_NAME.fullmatch(name):
                raise RuntimeError("A restore-prefixed database has an unsafe name; cleanup was refused.")
            if active_application_sessions(connection, name):
                raise RuntimeError(f"Refusing cleanup while application sessions use {name}.")
            target = replace(admin, database=name)
            with connect(target, database=name, app="OSTV SQL Restore Recovery Marker") as target_connection:
                require_marker(database_marker(target_connection), admin.ownership_marker, "restored database")
                disposable = str(
                    scalar(
                        target_connection,
                        "SELECT CONVERT(nvarchar(128), value) FROM sys.extended_properties WHERE class=0 AND name=?",
                        DISPOSABLE_PROPERTY,
                    )
                    or ""
                )
                if not disposable.startswith("restore-"):
                    raise RuntimeError("A restore database lacks the expected disposable marker.")
                uuid.UUID(disposable.removeprefix("restore-"))
            cursor = connection.cursor()
            try:
                cursor.execute(
                    f"ALTER DATABASE {quote_identifier(name)} SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
                    f"DROP DATABASE {quote_identifier(name)}"
                )
            finally:
                cursor.close()
            removed.append(name)
    return {"status": "restore-cleanup-complete", "removed": removed}


def lifecycle_test(config: DeploymentConfig) -> dict[str, object]:
    client = read_secret(_secret_path(config, "client"))
    verify_secret_matches(client, config, role="client")
    inventory = SqlSchemaInspector().inspect(_location(client, config.database), client.password)
    location = replace(_location(client, config.database), database_guid=inventory.database_guid)
    descriptor = DatabaseDescriptor.for_sql_server(
        location,
        schema_version=SQL_SCHEMA_V1.version,
    )
    registry = DatabaseDescriptorRegistry()
    registry.register(descriptor)

    class _CredentialStore:
        def read_password(self, _target: str) -> str:
            return client.password

        def write_password(self, _target: str, _username: str, _password: str) -> None:
            raise RuntimeError("Lifecycle validation credentials are read-only.")

        def delete_password(self, _target: str) -> None:
            raise RuntimeError("Lifecycle validation credentials are read-only.")

    credentials = _CredentialStore()
    remote_reader = SqlRemoteChangeReader(registry, credentials)
    store = SqlCollaborationStore(registry, credentials, remote_reader)
    session = store.start_session(
        descriptor.database_id,
        str(uuid.uuid4()),
        str(uuid.uuid4()),
        "sql-deployment-validation",
        "sql-server",
        APPLICATION_VERSION,
    )
    lock = None
    feed_valid = False
    try:
        store.heartbeat(
            descriptor.database_id,
            session.session_id,
            session.last_acknowledged_version,
            None,
            None,
            PresenceMode.VIEWING,
        )
        lock = store.acquire_lock(
            descriptor.database_id,
            session.session_id,
            ResourceRef("database", descriptor.database_id),
            "SQL deployment lifecycle validation",
        )
        poll = store.poll_changes(
            descriptor.database_id,
            session.last_acknowledged_version,
            1,
            session.session_id,
        )
        observed = poll.observed_batch
        feed_valid = bool(
            observed.feed_epoch
            and observed.minimum_valid_version <= observed.high_water_version
            and observed.delivered_through_version <= observed.high_water_version
        )
        if not feed_valid:
            raise RuntimeError("Initial collaboration feed reconciliation was not valid.")
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
            "sql-deployment-validation-complete",
        )
    with connect(client, database=config.database, app="OSTV SQL Lifecycle Cleanup Verification") as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT "
                "(SELECT COUNT(*) FROM [ostv].[Sessions] WHERE [SessionId]=? AND [DisconnectedAt] IS NULL), "
                "(SELECT COUNT(*) FROM [ostv].[Presence] WHERE [SessionId]=?), "
                "(SELECT COUNT(*) FROM [ostv].[Locks] WHERE [OwnerSessionId]=?)",
                session.session_id,
                session.session_id,
                session.session_id,
            )
            cleanup = tuple(int(value) for value in cursor.fetchone())
        finally:
            cursor.close()
    if cleanup != (0, 0, 0):
        raise RuntimeError("Application lifecycle validation left an active session, presence row, or lock.")
    return {
        "status": "lifecycle-valid",
        "session_started": True,
        "heartbeat_and_presence": True,
        "lease_acquire_release": True,
        "initial_feed_reconciliation": feed_valid,
        "active_sessions_after_close": cleanup[0],
        "presence_rows_after_close": cleanup[1],
        "locks_after_close": cleanup[2],
    }


def _location(secret: ConnectionSecret, database: str) -> SqlServerDatabaseLocation:
    return SqlServerDatabaseLocation(
        server=f"tcp:{secret.server},{secret.port}",
        database=database,
        authentication_mode=SqlAuthenticationMode.SQL_SERVER,
        username=secret.username,
        encrypt=True,
        trust_server_certificate=False,
        connection_timeout_seconds=10,
        command_timeout_seconds=600,
    )


def _drain_results(cursor: pyodbc.Cursor) -> None:
    while cursor.nextset():
        pass


def _redacted_error(error: Exception) -> str:
    passwords: list[str] = []
    for role in ("bootstrap", "admin", "client"):
        path = PRIVATE_STATE_ROOT / "secrets" / "container" / f"{role}.json"
        if not path.exists():
            continue
        try:
            passwords.append(read_secret(path).password)
        except RuntimeError:
            continue
    message = f"{type(error).__name__}: {error}"
    return redact_text(message, tuple(passwords))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the owned OST Visualizer SQL Server deployment.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("create-secrets")
    sub.add_parser("create-recovery-bootstrap")
    sub.add_parser("bootstrap-admin")
    sub.add_parser("provision")
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--with-backup-restore", action="store_true")
    sub.add_parser("backup")
    restore_parser = sub.add_parser("restore-verify")
    restore_parser.add_argument("path")
    migrate_parser = sub.add_parser("restore-migration")
    migrate_parser.add_argument("path")
    migrate_parser.add_argument("source_marker")
    migrate_parser.add_argument("expected_fingerprint")
    sub.add_parser("fingerprint")
    sub.add_parser("repair-permissions")
    sub.add_parser("rotate-client-password")
    sub.add_parser("uninstall-database")
    sub.add_parser("cleanup-restores")
    sub.add_parser("lifecycle-test")
    args = parser.parse_args(argv)
    try:
        config = load_config()
        if args.command == "create-secrets":
            result = create_secrets(config)
        elif args.command == "create-recovery-bootstrap":
            result = create_recovery_bootstrap(config)
        elif args.command == "bootstrap-admin":
            result = bootstrap_admin(config)
        elif args.command == "provision":
            result = provision_database(config)
        elif args.command == "validate":
            result = validate_environment(config, run_backup=args.with_backup_restore)
        elif args.command == "backup":
            result = {"status": "backup-complete", "path": str(backup_database(config))}
        elif args.command == "restore-verify":
            result = restore_verify(config, Path(args.path))
        elif args.command == "restore-migration":
            result = restore_migration(
                config,
                Path(args.path),
                Path(args.source_marker),
                Path(args.expected_fingerprint),
            )
        elif args.command == "fingerprint":
            result = database_fingerprint(config)
        elif args.command == "repair-permissions":
            result = repair_permissions(config)
        elif args.command == "rotate-client-password":
            result = rotate_client_password(config)
        elif args.command == "uninstall-database":
            result = uninstall_database(config)
        elif args.command == "cleanup-restores":
            result = cleanup_restore_databases(config)
        else:
            result = lifecycle_test(config)
    except Exception as exc:
        print(_redacted_error(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
