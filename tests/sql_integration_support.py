from __future__ import annotations
import os
import re
import secrets
import unittest
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import pyodbc
from ost_visualizer.application.interfaces.i_database_catalog import (
    DatabaseCatalogError,
)
from ost_visualizer.domain.entities.database_descriptor import (
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.sql.connection_manager import (
    SqlConnectionManager,
    SqlConnectionRequest,
)
from ost_visualizer.infrastructure.sql.credential_store import WindowsCredentialStore
from ost_visualizer.infrastructure.sql.database_creator import SqlDatabaseCreator

_TEST_DATABASE_PREFIX = "OSTV_IT_"
_SAFE_DATABASE_NAME = re.compile(r"\AOSTV_IT_[A-Za-z0-9_]+\Z", re.ASCII)
_RUN_MARKER_PROPERTY = "OSTVisualizerDisposableTestRun"
_SERVER_MARKER_PROPERTY = "OSTVisualizerDisposableTestServer"
_CREATE_PROCEDURE = "[ostv_it].[CreateDatabase]"
_DROP_PROCEDURE = "[ostv_it].[DropDatabase]"


@dataclass(frozen=True, repr=False)
class DisposableSqlConfiguration:
    location: SqlServerDatabaseLocation
    password: str
    server_marker: str

    def __repr__(self) -> str:
        return (
            "DisposableSqlConfiguration(location=<redacted>, "
            "password=<redacted>, server_marker=<redacted>)"
        )

    @classmethod
    def from_environment(cls) -> "DisposableSqlConfiguration":
        if os.environ.get("OSTV_SQL_INTEGRATION") != "1":
            raise unittest.SkipTest(
                "Set OSTV_SQL_INTEGRATION=1 to run disposable SQL integration tests."
            )
        if os.environ.get("OSTV_SQL_DESTRUCTIVE_TESTS") != "1":
            raise unittest.SkipTest(
                "Set OSTV_SQL_DESTRUCTIVE_TESTS=1 to authorize destructive "
                "disposable SQL tests."
            )
        server = os.environ.get("OSTV_SQL_TEST_SERVER", "").strip()
        if not server:
            raise unittest.SkipTest("OSTV_SQL_TEST_SERVER is not configured.")
        if server.casefold() not in {
            "localhost",
            "tcp:localhost",
            "localhost,1433",
            "tcp:localhost,1433",
        }:
            raise unittest.SkipTest(
                "The local SQL integration harness accepts only localhost on "
                "the default SQL Server port."
            )
        marker = os.environ.get("OSTV_SQL_TEST_SERVER_MARKER", "").strip()
        if not marker:
            raise unittest.SkipTest("OSTV_SQL_TEST_SERVER_MARKER is not configured.")
        mode = os.environ.get("OSTV_SQL_TEST_AUTH", "windows").strip().casefold()
        if mode not in {"windows", "sql"}:
            raise unittest.SkipTest("OSTV_SQL_TEST_AUTH must be 'windows' or 'sql'.")
        authentication = (
            SqlAuthenticationMode.SQL_SERVER
            if mode == "sql"
            else SqlAuthenticationMode.WINDOWS
        )
        username = os.environ.get("OSTV_SQL_TEST_USER", "").strip()
        password = _integration_password()
        if authentication == SqlAuthenticationMode.SQL_SERVER and (
            not username or not password
        ):
            raise unittest.SkipTest(
                "SQL authentication requires OSTV_SQL_TEST_USER and "
                "OSTV_SQL_TEST_CREDENTIAL_TARGET."
            )
        return cls(
            SqlServerDatabaseLocation(
                server=server,
                database="master",
                authentication_mode=authentication,
                username=username,
                encrypt=True,
                trust_server_certificate=False,
            ),
            password,
            marker,
        )


class DisposableSqlDatabase(AbstractContextManager):
    def __init__(self, configuration: DisposableSqlConfiguration) -> None:
        self.configuration = configuration
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.run_marker = secrets.token_hex(16)
        self.database_name = (
            f"{_TEST_DATABASE_PREFIX}{timestamp}_{os.getpid()}_"
            f"{self.run_marker[:12]}"
        )
        _require_test_database_name(self.database_name)
        self.connections = SqlConnectionManager()
        self.location = configuration.location
        self._marker_verified = False

    def __enter__(self) -> "DisposableSqlDatabase":
        self._create_database()
        self.location = replace(
            self.configuration.location, database=self.database_name
        )
        try:
            self._verify_server_marker()
            self._verify_database_marker()
            self._marker_verified = True
            creator = SqlDatabaseCreator(self.connections)
            result = creator.initialize_blank_database(
                self.location,
                self.configuration.password,
                application_version="integration-test",
                actor="OST Visualizer integration test",
            )
            self.location = result.location
            self._create_test_roles()
        except (DatabaseCatalogError, OSError, RuntimeError, ValueError, pyodbc.Error):
            if self._marker_verified:
                self.drop()
            raise
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> bool:
        self.drop()
        return False

    def _create_database(self) -> None:
        _require_test_database_name(self.database_name)
        self._verify_server_marker()
        request = self._master_request()
        with self.connections.connection(request, autocommit=True) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    f"EXEC {_CREATE_PROCEDURE} @DatabaseName=?, @RunMarker=?, "
                    "@ExpectedServerMarker=?",
                    self.database_name,
                    self.run_marker,
                    self.configuration.server_marker,
                )

    def drop(self) -> None:
        _require_test_database_name(self.database_name)
        self._verify_server_marker()
        if not self._database_exists():
            return
        self._verify_database_marker()
        request = self._master_request()
        with self.connections.connection(request, autocommit=True) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    f"EXEC {_DROP_PROCEDURE} @DatabaseName=?, @RunMarker=?, "
                    "@ExpectedServerMarker=?",
                    self.database_name,
                    self.run_marker,
                    self.configuration.server_marker,
                )

    def _verify_server_marker(self) -> None:
        request = self._master_request(read_only=True)
        with self.connections.connection(request, autocommit=True) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    "SELECT CONVERT(nvarchar(128), value) FROM "
                    "sys.extended_properties WHERE class=0 AND name=?",
                    _SERVER_MARKER_PROPERTY,
                )
                row = cursor.fetchone()
        if row is None or not secrets.compare_digest(
            str(row[0]), self.configuration.server_marker
        ):
            raise RuntimeError(
                "Refusing disposable SQL access because the server marker is invalid."
            )

    def _verify_database_marker(self) -> None:
        target = replace(self.configuration.location, database=self.database_name)
        request = SqlConnectionRequest(
            target,
            password=self.configuration.password,
            read_only=True,
        )
        with self.connections.connection(request, autocommit=True) as lease:
            with lease.cursor() as cursor:
                cursor.execute(
                    "SELECT CONVERT(nvarchar(128), value) FROM "
                    "sys.extended_properties WHERE class=0 AND name=?",
                    _RUN_MARKER_PROPERTY,
                )
                row = cursor.fetchone()
        if row is None or not secrets.compare_digest(str(row[0]), self.run_marker):
            raise RuntimeError(
                "Refusing disposable SQL access because the database marker is invalid."
            )

    def _database_exists(self) -> bool:
        request = self._master_request(read_only=True)
        with self.connections.connection(request, autocommit=True) as lease:
            with lease.cursor() as cursor:
                cursor.execute("SELECT DB_ID(?)", self.database_name)
                return cursor.fetchone()[0] is not None

    def _create_test_roles(self) -> None:
        self._verify_server_marker()
        self._verify_database_marker()
        request = SqlConnectionRequest(
            self.location,
            password=self.configuration.password,
        )
        with self.connections.connection(request, autocommit=False) as lease:
            committed = False
            try:
                with lease.cursor() as cursor:
                    cursor.execute(
                        "IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE "
                        "name=N'ostv_it') EXEC(N'CREATE SCHEMA [ostv_it] "
                        "AUTHORIZATION [dbo]')"
                    )
                    cursor.execute(
                        "CREATE ROLE [ostv_it_reader]; "
                        "CREATE ROLE [ostv_it_collaboration_admin]; "
                        "GRANT SELECT ON SCHEMA::[dbo] TO [ostv_it_reader]; "
                        "GRANT SELECT ON SCHEMA::[ostv] TO [ostv_it_reader]; "
                        "GRANT VIEW DEFINITION ON SCHEMA::[dbo] "
                        "TO [ostv_it_reader]; "
                        "GRANT VIEW DEFINITION ON SCHEMA::[ostv] "
                        "TO [ostv_it_reader]; "
                        "GRANT VIEW DATABASE STATE TO "
                        "[ostv_it_collaboration_admin]"
                    )
                lease.commit()
                committed = True
            finally:
                if not committed:
                    try:
                        lease.rollback()
                    except pyodbc.Error:
                        pass

    def _master_request(self, *, read_only: bool = False) -> SqlConnectionRequest:
        return SqlConnectionRequest(
            self.configuration.location,
            password=self.configuration.password,
            database_override="master",
            read_only=read_only,
        )


def _integration_password() -> str:
    target = os.environ.get("OSTV_SQL_TEST_CREDENTIAL_TARGET", "").strip()
    if not target:
        return ""
    return WindowsCredentialStore().read_password(target) or ""


def _require_test_database_name(database_name: str) -> None:
    if not _SAFE_DATABASE_NAME.fullmatch(database_name) or len(database_name) > 128:
        raise RuntimeError("Refusing a database name outside the OSTV_IT_ test scope.")
