from __future__ import annotations
import os
import secrets
import unittest
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
import pyodbc
from ost_visualizer.domain.entities.database_descriptor import (
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.sql.connection_manager import (
    SqlConnectionManager,
    SqlConnectionRequest,
)
from ost_visualizer.infrastructure.sql.database_creator import SqlDatabaseCreator

_TEST_DATABASE_PREFIX = "OSTV_IT_"
_RUN_MARKER_PROPERTY = "OSTVisualizerDisposableTestRun"


@dataclass(frozen=True, repr=False)
class DisposableSqlConfiguration:
    location: SqlServerDatabaseLocation
    password: str

    def __repr__(self) -> str:
        return (
            "DisposableSqlConfiguration("
            f"location={self.location!r}, password=<redacted>)"
        )

    @classmethod
    def from_environment(cls) -> "DisposableSqlConfiguration":
        if os.environ.get("OSTV_SQL_INTEGRATION") != "1":
            raise unittest.SkipTest(
                "Set OSTV_SQL_INTEGRATION=1 to run disposable SQL integration tests."
            )
        server = os.environ.get("OSTV_SQL_TEST_SERVER", "").strip()
        if not server:
            raise unittest.SkipTest("OSTV_SQL_TEST_SERVER is not configured.")
        mode = os.environ.get("OSTV_SQL_TEST_AUTH", "windows").strip().casefold()
        authentication = (
            SqlAuthenticationMode.SQL_SERVER
            if mode == "sql"
            else SqlAuthenticationMode.WINDOWS
        )
        username = os.environ.get("OSTV_SQL_TEST_USER", "").strip()
        password = os.environ.get("OSTV_SQL_TEST_PASSWORD", "")
        if authentication == SqlAuthenticationMode.SQL_SERVER and (
            not username or not password
        ):
            raise unittest.SkipTest(
                "SQL authentication requires OSTV_SQL_TEST_USER and "
                "OSTV_SQL_TEST_PASSWORD."
            )
        return cls(
            SqlServerDatabaseLocation(
                server=server,
                authentication_mode=authentication,
                username=username,
                encrypt=True,
                trust_server_certificate=True,
            ),
            password,
        )


class DisposableSqlDatabase(AbstractContextManager):
    def __init__(self, configuration: DisposableSqlConfiguration) -> None:
        self.configuration = configuration
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.run_marker = secrets.token_hex(12)
        self.database_name = (
            f"{_TEST_DATABASE_PREFIX}{timestamp}_{os.getpid()}_"
            f"{self.run_marker[:8]}"
        )
        self.connections = SqlConnectionManager()
        self.location = configuration.location

    def __enter__(self) -> "DisposableSqlDatabase":
        creator = SqlDatabaseCreator(self.connections)
        try:
            result = creator.create_database(
                self.location,
                self.database_name,
                self.configuration.password,
                application_version="integration-test",
                actor="OST Visualizer integration test",
            )
            self.location = result.location
            request = SqlConnectionRequest(
                self.location,
                password=self.configuration.password,
            )
            with self.connections.connection(request, autocommit=True) as lease:
                with lease.cursor() as cursor:
                    cursor.execute(
                        "EXEC sys.sp_addextendedproperty @name=?, @value=?",
                        _RUN_MARKER_PROPERTY,
                        self.run_marker,
                    )
        except (OSError, RuntimeError, ValueError, pyodbc.Error):
            self._drop_database(allow_missing_marker=True)
            raise
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self._drop_database(allow_missing_marker=False)
        return False

    def _drop_database(self, *, allow_missing_marker: bool) -> None:
        if not self.database_name.startswith(_TEST_DATABASE_PREFIX):
            raise RuntimeError("Refusing to delete a non-test SQL database.")
        if self.location.database == self.database_name:
            target_request = SqlConnectionRequest(
                self.location,
                password=self.configuration.password,
                read_only=True,
            )
            with self.connections.connection(target_request, autocommit=True) as lease:
                with lease.cursor() as cursor:
                    cursor.execute(
                        "SELECT CONVERT(nvarchar(128), value) FROM "
                        "sys.extended_properties WHERE class=0 AND name=?",
                        _RUN_MARKER_PROPERTY,
                    )
                    row = cursor.fetchone()
                    if not allow_missing_marker and (
                        row is None or str(row[0]) != self.run_marker
                    ):
                        raise RuntimeError(
                            "Refusing to delete a SQL database without its test marker."
                        )
        master_location = SqlServerDatabaseLocation(
            server=self.configuration.location.server,
            database="master",
            authentication_mode=self.configuration.location.authentication_mode,
            username=self.configuration.location.username,
            encrypt=self.configuration.location.encrypt,
            trust_server_certificate=(
                self.configuration.location.trust_server_certificate
            ),
        )
        master_request = SqlConnectionRequest(
            master_location,
            password=self.configuration.password,
        )
        with self.connections.connection(master_request, autocommit=True) as lease:
            with lease.cursor() as cursor:
                cursor.execute("SELECT DB_ID(?)", self.database_name)
                if cursor.fetchone()[0] is None:
                    return
                quoted = "[" + self.database_name.replace("]", "]]") + "]"
                cursor.execute(
                    f"ALTER DATABASE {quoted} SET SINGLE_USER "
                    "WITH ROLLBACK IMMEDIATE"
                )
                cursor.execute(f"DROP DATABASE {quoted}")
