from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generator, Iterable, Optional
import pyodbc
from ...domain.entities.database_descriptor import (
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
)
from .errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
    classify_pyodbc_error,
)
from ..database.connection_wrapper import CursorLease

_REQUIRED_DRIVER = "ODBC Driver 18 for SQL Server"


@dataclass(frozen=True, repr=False)
class SqlConnectionRequest:
    location: SqlServerDatabaseLocation
    password: str = ""
    database_override: Optional[str] = None
    read_only: bool = False

    def __repr__(self) -> str:
        return (
            "SqlConnectionRequest("
            f"location={self.location!r}, password=<redacted>, "
            f"database_override={self.database_override!r}, "
            f"read_only={self.read_only!r})"
        )


class SqlConnectionLease:
    def __init__(self, connection: pyodbc.Connection, command_timeout: int) -> None:
        self._connection = connection
        self._command_timeout = command_timeout
        self._cursors: list[CursorLease] = []
        self._closed = False

    def cursor(self) -> CursorLease:
        if self._closed:
            raise RuntimeError("SQL connection lease is closed")
        raw_cursor = self._connection.cursor()
        try:
            raw_cursor.timeout = self._command_timeout
        except (AttributeError, pyodbc.Error):
            pass
        cursor = CursorLease(self, raw_cursor)
        self._cursors.append(cursor)
        return cursor

    def _unregister_cursor(self, cursor: CursorLease) -> None:
        if cursor in self._cursors:
            self._cursors.remove(cursor)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def getinfo(self, info_type: int):
        return self._connection.getinfo(info_type)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for cursor in reversed(tuple(self._cursors)):
            try:
                cursor.close()
            except pyodbc.Error:
                pass
        self._cursors.clear()
        try:
            self._connection.close()
        except pyodbc.Error:
            pass


class SqlConnectionManager:
    def __init__(self, drivers: Optional[Iterable[str]] = None) -> None:
        available = tuple(drivers) if drivers is not None else tuple(pyodbc.drivers())
        self._driver = _REQUIRED_DRIVER if _REQUIRED_DRIVER in available else ""

    @property
    def driver(self) -> str:
        if not self._driver:
            raise SqlInfrastructureError(
                SqlErrorDetails(
                    SqlErrorCode.CONNECTION_FAILED,
                    "Microsoft ODBC Driver 18 for SQL Server is required.",
                )
            )
        return self._driver

    @contextmanager
    def connection(
        self,
        request: SqlConnectionRequest,
        *,
        autocommit: bool = False,
    ) -> Generator[SqlConnectionLease, None, None]:
        connection = None
        lease = None
        try:
            connection = pyodbc.connect(
                self.build_connection_string(request),
                autocommit=autocommit,
                timeout=request.location.connection_timeout_seconds,
            )
            try:
                connection.timeout = request.location.command_timeout_seconds
            except (AttributeError, pyodbc.Error):
                pass
            lease = SqlConnectionLease(
                connection, request.location.command_timeout_seconds
            )
            yield lease
        except pyodbc.Error as exc:
            raise SqlInfrastructureError(classify_pyodbc_error(exc)) from None
        finally:
            if lease is not None:
                lease.close()
            elif connection is not None:
                try:
                    connection.close()
                except pyodbc.Error:
                    pass

    def build_connection_string(self, request: SqlConnectionRequest) -> str:
        location = request.location
        database = request.database_override
        if database is None:
            database = location.database or "master"
        parts = [
            f"DRIVER={_brace(self.driver)}",
            f"SERVER={_brace(_normalize_server(location.server))}",
            f"DATABASE={_brace(database)}",
            f"Encrypt={'yes' if location.encrypt else 'no'}",
            "TrustServerCertificate="
            f"{'yes' if location.trust_server_certificate else 'no'}",
            f"Connection Timeout={location.connection_timeout_seconds}",
            "MARS_Connection=no",
            "APP=OST Visualizer",
        ]
        if request.read_only:
            parts.append("ApplicationIntent=ReadOnly")
        if location.authentication_mode == SqlAuthenticationMode.WINDOWS:
            parts.append("Trusted_Connection=yes")
        else:
            if not location.username or not request.password:
                raise ValueError("SQL Server username and password are required")
            parts.extend(
                (
                    f"UID={_brace(location.username)}",
                    f"PWD={_brace(request.password)}",
                )
            )
        return ";".join(parts) + ";"


def _brace(value: str) -> str:
    if "\x00" in value:
        raise ValueError("SQL connection value contains a null character")
    return "{" + value.replace("}", "}}") + "}"


def _normalize_server(server: str) -> str:
    value = server.strip()
    if not value:
        raise ValueError("SQL Server name is required")
    if "," in value and not value.casefold().startswith("tcp:"):
        return "tcp:" + value
    return value
