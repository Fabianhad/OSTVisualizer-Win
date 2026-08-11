from __future__ import annotations
import argparse
import hmac
import ipaddress
import json
import os
import re
import stat
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal
import pyodbc

# Administration commands are short-lived. Disabling pooling guarantees that a
# closed context also closes its SQL session before guarded cleanup continues.
pyodbc.pooling = False
PRIVATE_STATE_ROOT = Path("/home/SQLServer")
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEPLOYMENT_PROPERTY = "OSTVisualizerUbuntuDeployment"
DEPLOYMENT_KIND_PROPERTY = "OSTVisualizerDeploymentKind"
DATABASE_PROPERTY = "OSTVisualizerUbuntuDatabase"
BACKUP_PROPERTY = "OSTVisualizerUbuntuBackupDirectory"
DISPOSABLE_PROPERTY = "OSTVisualizerDisposableTestRun"
EXPECTED_DRIVER = "ODBC Driver 18 for SQL Server"
SAFE_SQL_IDENTIFIER = re.compile(r"\A[A-Za-z][A-Za-z0-9_]{0,127}\Z", re.ASCII)
SAFE_CONTAINER_NAME = re.compile(r"\A[A-Za-z][A-Za-z0-9_.-]{0,127}\Z", re.ASCII)
SAFE_INTERFACE_NAME = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_.-]{0,14}\Z", re.ASCII)
SAFE_DNS_NAME = re.compile(
    r"\A[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\Z", re.ASCII
)
PINNED_SQL_IMAGE = re.compile(
    r"\Amcr\.microsoft\.com/mssql/server:2025-CU[0-9]+-ubuntu-24\.04@sha256:[0-9a-f]{64}\Z",
    re.ASCII,
)
ENVIRONMENT_KEYS = frozenset(
    {
        "OSTV_STATE_ROOT",
        "OSTV_SQL_IMAGE",
        "OSTV_CONTAINER_NAME",
        "OSTV_DEPLOYMENT_ID",
        "OSTV_SQL_EDITION",
        "OSTV_SA_PASSWORD",
        "OSTV_SQL_DATABASE",
        "OSTV_SQL_ADMIN_LOGIN",
        "OSTV_SQL_CLIENT_LOGIN",
        "OSTV_SQL_HOST_PORT",
        "OSTV_SQL_VPN_PORT",
        "OSTV_SQL_PUBLIC_BIND_ADDRESS",
        "OSTV_SQL_PUBLIC_PORT",
        "OSTV_SQL_ALLOWED_SOURCE_CIDR",
        "OSTV_SQL_CERTIFICATE_NAME",
        "OSTV_WG_INTERFACE",
        "OSTV_WG_SERVER_ADDRESS",
        "OSTV_WG_PREFIX_LENGTH",
        "OSTV_WG_LISTEN_PORT",
        "OSTV_PUBLIC_INTERFACE",
        "OSTV_PUBLIC_ENDPOINT",
        "OSTV_DOCKER_NETWORK",
        "OSTV_DOCKER_SUBNET",
        "OSTV_SQL_CONTAINER_ADDRESS",
    }
)
NON_SECRET_ENVIRONMENT_KEYS = ENVIRONMENT_KEYS - {"OSTV_SA_PASSWORD"}


@dataclass(frozen=True, repr=False)
class ConnectionSecret:
    server: str
    port: int
    database: str
    username: str
    password: str
    encrypt: bool
    trust_server_certificate: bool
    ownership_marker: str

    def __repr__(self) -> str:
        return "ConnectionSecret(<redacted>)"


@dataclass(frozen=True)
class DeploymentConfig:
    server: str
    port: int
    database: str
    admin_login: str
    client_login: str
    edition: str
    secrets_directory: Path
    ownership_marker_file: Path
    backup_host_directory: Path
    backup_sql_directory: Path
    data_sql_directory: Path
    container_name: str


def load_config() -> DeploymentConfig:
    values = load_environment()
    return DeploymentConfig(
        server=values["OSTV_SQL_CERTIFICATE_NAME"],
        port=_port(values, "OSTV_SQL_HOST_PORT"),
        database=values["OSTV_SQL_DATABASE"],
        admin_login=values["OSTV_SQL_ADMIN_LOGIN"],
        client_login=values["OSTV_SQL_CLIENT_LOGIN"],
        edition=values["OSTV_SQL_EDITION"],
        secrets_directory=PRIVATE_STATE_ROOT / "secrets" / "container",
        ownership_marker_file=PRIVATE_STATE_ROOT / "ownership" / "container-marker",
        backup_host_directory=PRIVATE_STATE_ROOT / "backups",
        backup_sql_directory=Path("/var/opt/mssql/backup"),
        data_sql_directory=Path("/var/opt/mssql/data"),
        container_name=values["OSTV_CONTAINER_NAME"],
    )


def config_value(key: str) -> str:
    if key not in NON_SECRET_ENVIRONMENT_KEYS:
        raise RuntimeError(
            "The requested configuration key is not available to shell callers."
        )
    return load_environment()[key]


def read_secret(path: Path) -> ConnectionSecret:
    require_private_file(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Credential file is unreadable: {path.name}") from exc
    expected = {
        "server",
        "port",
        "database",
        "username",
        "password",
        "encrypt",
        "trust_server_certificate",
        "ownership_marker",
    }
    string_keys = expected - {"port", "encrypt", "trust_server_certificate"}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise RuntimeError(f"Credential file has an invalid shape: {path.name}")
    if (
        any(not isinstance(payload[key], str) for key in string_keys)
        or type(payload["port"]) is not int
        or type(payload["encrypt"]) is not bool
        or type(payload["trust_server_certificate"]) is not bool
    ):
        raise RuntimeError(f"Credential file has invalid types: {path.name}")
    return ConnectionSecret(**payload)


def write_secret(path: Path, secret: ConnectionSecret) -> None:
    payload = {
        "server": secret.server,
        "port": secret.port,
        "database": secret.database,
        "username": secret.username,
        "password": secret.password,
        "encrypt": secret.encrypt,
        "trust_server_certificate": secret.trust_server_certificate,
        "ownership_marker": secret.ownership_marker,
    }
    atomic_write_private(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def atomic_write_private(path: Path, content: str) -> None:
    _require_under_private_root(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def verify_secret_matches(
    secret: ConnectionSecret,
    config: DeploymentConfig,
    *,
    role: Literal["admin", "client"],
) -> None:
    expected_user = config.admin_login if role == "admin" else config.client_login
    if (
        secret.server != config.server
        or secret.port != config.port
        or secret.database != config.database
        or secret.username != expected_user
        or secret.encrypt is not True
        or secret.trust_server_certificate is not False
        or not secret.ownership_marker
    ):
        raise RuntimeError(
            f"The {role} credential does not match the deployment configuration."
        )


@contextmanager
def connect(
    secret: ConnectionSecret,
    *,
    database: str | None = None,
    app: str = "OSTV SQL Admin",
    autocommit: bool = True,
) -> Iterator[pyodbc.Connection]:
    if EXPECTED_DRIVER not in pyodbc.drivers():
        raise RuntimeError(f"{EXPECTED_DRIVER} is required.")
    target = database if database is not None else secret.database
    if not SAFE_SQL_IDENTIFIER.fullmatch(target):
        raise RuntimeError("Refusing an unsafe SQL database identifier.")
    connection_string = (
        ";".join(
            (
                f"DRIVER={_brace(EXPECTED_DRIVER)}",
                f"SERVER={_brace(f'tcp:{secret.server},{secret.port}')}",
                f"DATABASE={_brace(target)}",
                f"UID={_brace(secret.username)}",
                f"PWD={_brace(secret.password)}",
                "Encrypt=yes",
                "TrustServerCertificate=no",
                "Connection Timeout=10",
                "MARS_Connection=no",
                f"APP={_brace(app)}",
            )
        )
        + ";"
    )
    connection = pyodbc.connect(connection_string, autocommit=autocommit, timeout=10)
    try:
        yield connection
    finally:
        connection.close()


def scalar(connection: pyodbc.Connection, sql: str, *params: object) -> object | None:
    cursor = connection.cursor()
    try:
        cursor.execute(sql, *params)
        row = cursor.fetchone()
        return None if row is None else row[0]
    finally:
        cursor.close()


def server_marker(connection: pyodbc.Connection) -> str:
    value = scalar(
        connection,
        "SELECT CONVERT(nvarchar(128), value) FROM sys.extended_properties WHERE class=0 AND name=?",
        DEPLOYMENT_PROPERTY,
    )
    return str(value or "")


def database_marker(connection: pyodbc.Connection) -> str:
    value = scalar(
        connection,
        "SELECT CONVERT(nvarchar(128), value) FROM sys.extended_properties WHERE class=0 AND name=?",
        DATABASE_PROPERTY,
    )
    return str(value or "")


def require_marker(actual: str, expected: str, label: str) -> None:
    if not actual or not expected or not hmac.compare_digest(actual, expected):
        raise RuntimeError(
            f"Refusing operation because the {label} ownership marker does not match."
        )


def set_extended_property(cursor: pyodbc.Cursor, name: str, value: str) -> None:
    cursor.execute(
        "IF EXISTS (SELECT 1 FROM sys.extended_properties WHERE class=0 AND name=?) "
        "EXEC sys.sp_updateextendedproperty @name=?, @value=? "
        "ELSE EXEC sys.sp_addextendedproperty @name=?, @value=?",
        name,
        name,
        value,
        name,
        value,
    )


def quote_identifier(value: str) -> str:
    if not SAFE_SQL_IDENTIFIER.fullmatch(value):
        raise RuntimeError("Refusing an unsafe SQL identifier.")
    return f"[{value}]"


def active_application_sessions(
    connection: pyodbc.Connection, database_name: str
) -> int:
    return int(
        scalar(
            connection,
            "SELECT COUNT(*) FROM sys.dm_exec_sessions WHERE database_id=DB_ID(?) "
            "AND (program_name=N'OST Visualizer' OR program_name LIKE N'OST Visualizer%')",
            database_name,
        )
        or 0
    )


def require_private_file(path: Path, *, label: str = "credential file") -> None:
    _require_under_private_root(path)
    if path.is_symlink():
        raise RuntimeError(f"Required {label} must not be a symbolic link: {path.name}")
    try:
        metadata = path.stat()
    except OSError as exc:
        raise RuntimeError(f"Required {label} is missing: {path.name}") from exc
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise RuntimeError(f"The {label} permissions must be 0600: {path.name}")
    if metadata.st_uid != 0:
        raise RuntimeError(f"The {label} must be owned by root: {path.name}")


def require_private_directory(path: Path, *, label: str) -> None:
    _require_under_private_root(path)
    if path.is_symlink():
        raise RuntimeError(f"Required {label} must not be a symbolic link: {path.name}")
    try:
        metadata = path.stat()
    except OSError as exc:
        raise RuntimeError(f"Required {label} is missing: {path.name}") from exc
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise RuntimeError(f"The {label} permissions must be 0700: {path.name}")
    if metadata.st_uid != 0:
        raise RuntimeError(f"The {label} must be owned by root: {path.name}")


def redact_text(text: str, secrets: tuple[str, ...]) -> str:
    redacted = text
    for secret in sorted((value for value in secrets if value), key=len, reverse=True):
        redacted = redacted.replace(secret, "<redacted>")
    return redacted


def load_environment() -> dict[str, str]:
    _require_private_root()
    path = PRIVATE_STATE_ROOT / ".env"
    require_private_file(path, label="deployment configuration")
    values = _read_env_file(path)
    if set(values) != ENVIRONMENT_KEYS:
        raise RuntimeError(
            "The private deployment configuration has an invalid key set."
        )
    if values["OSTV_STATE_ROOT"] != str(PRIVATE_STATE_ROOT):
        raise RuntimeError(f"OSTV_STATE_ROOT must be exactly {PRIVATE_STATE_ROOT}.")
    unresolved = {key for key, value in values.items() if "<" in value or ">" in value}
    if unresolved - {"OSTV_SA_PASSWORD"} or (
        unresolved and values["OSTV_SA_PASSWORD"] != "<GENERATED_BY_SETUP>"
    ):
        raise RuntimeError(
            "The private deployment configuration contains unresolved placeholders."
        )
    if not PINNED_SQL_IMAGE.fullmatch(values["OSTV_SQL_IMAGE"]):
        raise RuntimeError(
            "OSTV_SQL_IMAGE must be an official digest-pinned SQL Server 2025 image."
        )
    for key in ("OSTV_SQL_DATABASE", "OSTV_SQL_ADMIN_LOGIN", "OSTV_SQL_CLIENT_LOGIN"):
        if not SAFE_SQL_IDENTIFIER.fullmatch(values[key]):
            raise RuntimeError(f"The configured SQL identifier {key} is invalid.")
    if not SAFE_CONTAINER_NAME.fullmatch(values["OSTV_CONTAINER_NAME"]):
        raise RuntimeError("The configured container name is invalid.")
    if not SAFE_CONTAINER_NAME.fullmatch(values["OSTV_DOCKER_NETWORK"]):
        raise RuntimeError("The configured Docker network name is invalid.")
    if values["OSTV_SQL_EDITION"] not in {
        "Express",
        "Developer",
        "Standard",
        "Enterprise",
    }:
        raise RuntimeError("The configured SQL Server edition is invalid.")
    for key in ("OSTV_WG_INTERFACE", "OSTV_PUBLIC_INTERFACE"):
        if not SAFE_INTERFACE_NAME.fullmatch(values[key]):
            raise RuntimeError(f"The configured interface name {key} is invalid.")
    if not SAFE_DNS_NAME.fullmatch(values["OSTV_SQL_CERTIFICATE_NAME"]):
        raise RuntimeError("The configured SQL certificate name is invalid.")
    try:
        ipaddress.ip_address(values["OSTV_PUBLIC_ENDPOINT"])
    except ValueError:
        if not SAFE_DNS_NAME.fullmatch(values["OSTV_PUBLIC_ENDPOINT"]):
            raise RuntimeError("The configured public WireGuard endpoint is invalid.")
    for key in (
        "OSTV_SQL_HOST_PORT",
        "OSTV_SQL_VPN_PORT",
        "OSTV_SQL_PUBLIC_PORT",
        "OSTV_WG_LISTEN_PORT",
    ):
        _port(values, key)
    try:
        uuid.UUID(values["OSTV_DEPLOYMENT_ID"])
        wireguard = ipaddress.ip_interface(
            f'{values["OSTV_WG_SERVER_ADDRESS"]}/{values["OSTV_WG_PREFIX_LENGTH"]}'
        )
        docker_network = ipaddress.ip_network(values["OSTV_DOCKER_SUBNET"], strict=True)
        container_address = ipaddress.ip_address(values["OSTV_SQL_CONTAINER_ADDRESS"])
        public_bind_address = ipaddress.ip_address(
            values["OSTV_SQL_PUBLIC_BIND_ADDRESS"]
        )
        allowed_sources = tuple(
            ipaddress.ip_network(source, strict=True)
            for source in values["OSTV_SQL_ALLOWED_SOURCE_CIDR"].split(",")
        )
    except ValueError as exc:
        raise RuntimeError(
            "The private deployment contains an invalid UUID, address, or subnet."
        ) from exc
    if (
        public_bind_address.version != 4
        or not public_bind_address.is_global
        or not allowed_sources
        or len(set(allowed_sources)) != len(allowed_sources)
        or any(
            source.version != 4 or source.prefixlen != 32 or not source.is_global
            for source in allowed_sources
        )
    ):
        raise RuntimeError(
            "Public SQL access requires one global IPv4 bind address and one or more unique global IPv4 /32 sources."
        )
    if wireguard.version != docker_network.version:
        raise RuntimeError(
            "The WireGuard and Docker subnets must use the same address family."
        )
    if wireguard.ip in {
        wireguard.network.network_address,
        wireguard.network.broadcast_address,
    }:
        raise RuntimeError("The WireGuard server address is not usable.")
    if container_address not in docker_network or container_address in {
        docker_network.network_address,
        docker_network.broadcast_address,
    }:
        raise RuntimeError(
            "The SQL container address is not usable in the Docker subnet."
        )
    if wireguard.network.overlaps(docker_network):
        raise RuntimeError("The WireGuard and Docker subnets must not overlap.")
    return values


def _read_env_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(
            "The private deployment configuration is unreadable."
        ) from exc
    result: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise RuntimeError("The private deployment configuration is malformed.")
        key, value = line.split("=", 1)
        if (
            not key
            or key in result
            or not value
            or any(character.isspace() for character in key)
        ):
            raise RuntimeError("The private deployment configuration is malformed.")
        result[key] = value
    return result


def _require_private_root() -> None:
    root = PRIVATE_STATE_ROOT
    if root.is_symlink():
        raise RuntimeError(
            f"The private state root must not be a symbolic link: {root}"
        )
    try:
        metadata = root.stat()
    except OSError as exc:
        raise RuntimeError(f"Required private state root is missing: {root}") from exc
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise RuntimeError(
            f"The private state root must be a mode-0700 directory: {root}"
        )
    if metadata.st_uid != 0:
        raise RuntimeError(f"The private state root must be owned by root: {root}")


def _require_under_private_root(path: Path) -> None:
    try:
        root = PRIVATE_STATE_ROOT.resolve(strict=True)
        parent = path.parent.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(
            "The private deployment path has a missing parent directory."
        ) from exc
    if root not in parent.parents and parent != root:
        raise RuntimeError(
            f"Private deployment files must be under {PRIVATE_STATE_ROOT}."
        )


def _port(values: dict[str, str], key: str) -> int:
    try:
        value = int(values[key])
    except (KeyError, ValueError) as exc:
        raise RuntimeError(f"The configured port {key} is invalid.") from exc
    if not 1 <= value <= 65535:
        raise RuntimeError(f"The configured port {key} is invalid.")
    return value


def _brace(value: str) -> str:
    if "\x00" in value:
        raise RuntimeError("SQL connection value contains a null byte.")
    return "{" + value.replace("}", "}}") + "}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read validated public deployment configuration."
    )
    parser.add_argument("command", choices=("get", "validate"))
    parser.add_argument("key", nargs="?")
    args = parser.parse_args(argv)
    try:
        if args.command == "get":
            if args.key is None:
                parser.error("A configuration key is required.")
            print(config_value(args.key), end="")
        elif args.key is not None:
            parser.error("The validate command does not accept a key.")
        else:
            load_config()
    except RuntimeError as exc:
        print(f"Configuration error: {exc}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
