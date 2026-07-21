from __future__ import annotations
import os
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional, Union

_ACCESS_DATABASE_NAMESPACE = uuid.UUID("c6e62f04-915a-4b50-bf67-80bdb299f9b5")
_SQL_DATABASE_NAMESPACE = uuid.UUID("be25d43e-289f-41ad-958e-ad0f7950b00a")


class DatabaseBackend(str, Enum):
    ACCESS = "access"
    SQL_SERVER = "sql_server"


class SqlAuthenticationMode(str, Enum):
    WINDOWS = "windows"
    SQL_SERVER = "sql_server"


@dataclass(frozen=True)
class AccessDatabaseLocation:
    file_path: str

    def to_dict(self) -> dict[str, object]:
        return {"file_path": self.file_path}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "AccessDatabaseLocation":
        _require_exact_keys(data, {"file_path"}, "Access database location")
        file_path = _saved_string(
            data,
            "file_path",
            "Access database location",
            required=True,
            strip=True,
        )
        return cls(file_path=file_path)


@dataclass(frozen=True, repr=False)
class SqlServerDatabaseLocation:
    server: str
    database: str
    authentication_mode: SqlAuthenticationMode = SqlAuthenticationMode.WINDOWS
    username: str = ""
    database_guid: str = ""
    encrypt: bool = True
    trust_server_certificate: bool = False
    connection_timeout_seconds: int = 10
    command_timeout_seconds: int = 30

    def __repr__(self) -> str:
        return (
            "SqlServerDatabaseLocation("
            f"server={self.server!r}, database={self.database!r}, "
            f"authentication_mode={self.authentication_mode!r}, "
            f"username={self.username!r}, database_guid={self.database_guid!r}, "
            f"encrypt={self.encrypt!r}, "
            "trust_server_certificate="
            f"{self.trust_server_certificate!r}, "
            f"connection_timeout_seconds={self.connection_timeout_seconds!r}, "
            f"command_timeout_seconds={self.command_timeout_seconds!r})"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "server": self.server,
            "database": self.database,
            "authentication_mode": self.authentication_mode.value,
            "username": self.username,
            "database_guid": self.database_guid,
            "encrypt": self.encrypt,
            "trust_server_certificate": self.trust_server_certificate,
            "connection_timeout_seconds": self.connection_timeout_seconds,
            "command_timeout_seconds": self.command_timeout_seconds,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "SqlServerDatabaseLocation":
        _require_exact_keys(
            data,
            {
                "server",
                "database",
                "authentication_mode",
                "username",
                "database_guid",
                "encrypt",
                "trust_server_certificate",
                "connection_timeout_seconds",
                "command_timeout_seconds",
            },
            "SQL Server database location",
        )
        raw_auth = _saved_string(
            data,
            "authentication_mode",
            "SQL Server location",
            required=True,
        )
        auth_mode = SqlAuthenticationMode(raw_auth)
        server = _saved_string(
            data, "server", "SQL Server location", required=True, strip=True
        )
        database = _saved_string(
            data, "database", "SQL Server location", required=True, strip=True
        )
        return cls(
            server=server,
            database=database,
            authentication_mode=auth_mode,
            username=_saved_string(data, "username", "SQL Server location"),
            database_guid=_saved_string(data, "database_guid", "SQL Server location"),
            encrypt=_saved_bool(data, "encrypt"),
            trust_server_certificate=_saved_bool(data, "trust_server_certificate"),
            connection_timeout_seconds=_saved_timeout(
                data, "connection_timeout_seconds", maximum=60
            ),
            command_timeout_seconds=_saved_timeout(
                data, "command_timeout_seconds", maximum=600
            ),
        )


DatabaseLocation = Union[AccessDatabaseLocation, SqlServerDatabaseLocation]


@dataclass(frozen=True, repr=False)
class DatabaseDescriptor:
    database_id: str
    backend: DatabaseBackend
    display_name: str
    location: DatabaseLocation
    schema_version: int = 0

    def __repr__(self) -> str:
        return (
            "DatabaseDescriptor("
            f"database_id={self.database_id!r}, backend={self.backend!r}, "
            f"display_name={self.display_name!r}, location={self.location!r}, "
            f"schema_version={self.schema_version!r})"
        )

    @classmethod
    def for_access(
        cls,
        file_path: str,
        *,
        display_name: Optional[str] = None,
        database_id: Optional[str] = None,
        schema_version: int = 0,
    ) -> "DatabaseDescriptor":
        normalized = os.path.normcase(os.path.abspath(os.path.normpath(file_path)))
        stable_id = database_id or str(
            uuid.uuid5(_ACCESS_DATABASE_NAMESPACE, normalized)
        )
        if display_name is None:
            display_name = os.path.splitext(os.path.basename(file_path))[0]
        return cls(
            database_id=stable_id,
            backend=DatabaseBackend.ACCESS,
            display_name=display_name or os.path.basename(file_path),
            location=AccessDatabaseLocation(file_path=file_path),
            schema_version=schema_version,
        )

    @classmethod
    def for_sql_server(
        cls,
        location: SqlServerDatabaseLocation,
        *,
        display_name: Optional[str] = None,
        database_id: Optional[str] = None,
        schema_version: int,
    ) -> "DatabaseDescriptor":
        identity = location.database_guid.strip().lower()
        if not identity:
            identity = "|".join(
                (
                    location.server.strip().casefold(),
                    location.database.strip().casefold(),
                    location.authentication_mode.value,
                    location.username.strip().casefold(),
                )
            )
        if schema_version < 0:
            raise ValueError("Database schema version cannot be negative")
        stable_id = database_id or str(uuid.uuid5(_SQL_DATABASE_NAMESPACE, identity))
        return cls(
            database_id=stable_id,
            backend=DatabaseBackend.SQL_SERVER,
            display_name=display_name or location.database,
            location=location,
            schema_version=schema_version,
        )

    @property
    def access_path(self) -> str:
        if isinstance(self.location, AccessDatabaseLocation):
            return self.location.file_path
        return ""

    @property
    def sql_location(self) -> SqlServerDatabaseLocation:
        if isinstance(self.location, SqlServerDatabaseLocation):
            return self.location
        raise TypeError("Database descriptor is not for SQL Server")

    def to_dict(self) -> dict[str, object]:
        return {
            "database_id": self.database_id,
            "backend": self.backend.value,
            "display_name": self.display_name,
            "location": self.location.to_dict(),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "DatabaseDescriptor":
        _require_exact_keys(
            data,
            {
                "database_id",
                "backend",
                "display_name",
                "location",
                "schema_version",
            },
            "database descriptor",
        )
        raw_backend = _saved_string(
            data, "backend", "database descriptor", required=True
        )
        backend = DatabaseBackend(raw_backend)
        location_data = data.get("location")
        if not isinstance(location_data, dict):
            raise ValueError("Saved database location is missing")
        database_id = _saved_string(
            data, "database_id", "database descriptor", required=True, strip=True
        )
        display_name = _saved_string(
            data, "display_name", "database descriptor", required=True, strip=True
        )
        schema_version = _saved_schema_version(data)
        if backend == DatabaseBackend.SQL_SERVER:
            location = SqlServerDatabaseLocation.from_dict(location_data)
            return cls.for_sql_server(
                location,
                display_name=display_name,
                database_id=database_id,
                schema_version=schema_version,
            )
        location = AccessDatabaseLocation.from_dict(location_data)
        return cls.for_access(
            location.file_path,
            display_name=display_name,
            database_id=database_id,
            schema_version=schema_version,
        )


def credential_target_for(database_id: str) -> str:
    return f"OSTVisualizer/SqlServer/{database_id}"


def validate_sql_database_name(name: str) -> None:
    if not name or len(name) > 128 or name != name.strip():
        raise ValueError(
            "Database names must be 1 to 128 characters without leading or "
            "trailing spaces."
        )
    if any(ord(character) < 32 for character in name):
        raise ValueError("Database name contains a control character.")
    if name.casefold() in {"master", "model", "msdb", "tempdb"}:
        raise ValueError("A SQL Server system database cannot be used.")


def _saved_bool(data: Mapping[str, object], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"Saved SQL Server {key} value is invalid")
    return value


def _saved_timeout(data: Mapping[str, object], key: str, *, maximum: int) -> int:
    value = data.get(key)
    if type(value) is not int:
        raise ValueError(f"Saved SQL Server {key} value is invalid")
    parsed = value
    if parsed < 1 or parsed > maximum:
        raise ValueError(f"Saved SQL Server {key} value is out of range")
    return parsed


def _saved_schema_version(data: Mapping[str, object]) -> int:
    value = data.get("schema_version")
    if type(value) is not int:
        raise ValueError("Saved database schema version is invalid")
    version = value
    if version < 0:
        raise ValueError("Saved database schema version is invalid")
    return version


def _saved_string(
    data: Mapping[str, object],
    key: str,
    label: str,
    *,
    required: bool = False,
    strip: bool = False,
) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Saved {label} {key} value is invalid")
    if strip:
        value = value.strip()
    if required and not value:
        raise ValueError(f"Saved {label} {key} value is missing")
    return value


def _require_exact_keys(
    data: Mapping[str, object], expected: set[str], label: str
) -> None:
    if set(data) != expected:
        raise ValueError(f"Saved {label} has an unsupported format")
