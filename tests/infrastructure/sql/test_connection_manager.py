from tests.helpers.sql.collaboration import (
    SQL_SCHEMA_V1,
    DatabaseCapabilityService,
    DatabaseDescriptor,
    DatabaseDescriptorRegistry,
    DatabaseSessionRegistry,
    SqlServerDatabaseLocation,
    _CollaborationStore,
    _coordinator,
    _Dispatcher,
    _EventBus,
    _PermissionProbe,
    _Reconciliation,
    _RemoteReader,
    _shutdown_coordinator,
    _token_service,
)
from ost_visualizer.infrastructure.sql.connection_manager import (
    SqlConnectionManager,
    SqlConnectionRequest,
)
from unittest.mock import Mock, patch
import unittest
import os
from unittest.mock import patch
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
    credential_target_for,
)
from ost_visualizer.infrastructure.sql.connection_manager import (
    SqlConnectionLease,
    SqlConnectionManager,
    SqlConnectionRequest,
)
from tests.helpers.sql.cleanup_support import (
    _RawConnection as _cleanup_support__RawConnection,
    _RawCursor as _cleanup_support__RawCursor,
)
import secrets
import pyodbc
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlInfrastructureError,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
    credential_target_for,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class SqlConnectionTimeoutTests(unittest.TestCase):
    def test_login_timeout_is_separate_from_command_timeout(self):
        request = SqlConnectionRequest(
            SqlServerDatabaseLocation(
                server="localhost",
                database="TEST",
                connection_timeout_seconds=7,
                command_timeout_seconds=43,
            )
        )
        manager = SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])
        raw = Mock()
        with patch(
            "ost_visualizer.infrastructure.sql.connection_manager.pyodbc.connect",
            return_value=raw,
        ) as connect:
            with manager.connection(request) as lease:
                self.assertIsNotNone(lease)
                self.assertEqual(raw.timeout, 43)
            self.assertEqual(connect.call_args.kwargs["timeout"], 7)
            self.assertIs(connect.call_args.kwargs["autocommit"], False)
            self.assertIn("Connection Timeout=7;", connect.call_args.args[0])
            self.assertNotIn("43", connect.call_args.args[0])
            raw.close.assert_called_once_with()

    def test_connection_failure_is_classified_and_never_yields_a_lease(self):
        manager = SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])
        request = SqlConnectionRequest(
            SqlServerDatabaseLocation(server="localhost", database="TEST")
        )
        with patch(
            "ost_visualizer.infrastructure.sql.connection_manager.pyodbc.connect",
            side_effect=pyodbc.Error("28000", "Login failed for user (18456)"),
        ):
            with self.assertRaises(SqlInfrastructureError) as caught:
                with manager.connection(request):
                    self.fail("a failed connect must not yield a lease")
        self.assertEqual(
            caught.exception.details.code, SqlErrorCode.AUTHENTICATION_FAILED
        )
        self.assertTrue(caught.exception.credential_required)


class ConnectionManagerSqlCleanupTests(unittest.TestCase):
    def test_sql_connection_lease_close_is_idempotent(self):
        raw_connection = _cleanup_support__RawConnection()
        lease = SqlConnectionLease(raw_connection, 30)
        cursor = lease.cursor()
        self.assertEqual(raw_connection.raw_cursor.timeout, 30)
        lease.close()
        lease.close()
        self.assertEqual(raw_connection.close_count, 1)
        self.assertEqual(raw_connection.raw_cursor.close_count, 1)
        cursor.close()
        self.assertEqual(raw_connection.raw_cursor.close_count, 1)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            lease.cursor()

    def test_exception_inside_connection_block_still_closes_cursor_and_connection(
        self,
    ):
        raw_connection = _cleanup_support__RawConnection()
        manager = SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])
        request = SqlConnectionRequest(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        with patch(
            "ost_visualizer.infrastructure.sql.connection_manager.pyodbc.connect",
            return_value=raw_connection,
        ):
            with self.assertRaisesRegex(ValueError, "boom"):
                with manager.connection(request) as lease:
                    lease.cursor()
                    raise ValueError("boom")
        self.assertEqual(raw_connection.close_count, 1)
        self.assertEqual(raw_connection.raw_cursor.close_count, 1)

    def test_cursor_close_failure_does_not_leave_connection_open(self):
        raw_connection = _cleanup_support__RawConnection()

        def failing_close():
            raw_connection.raw_cursor.close_count += 1
            raise pyodbc.Error("HY000", "cursor close failed")

        raw_connection.raw_cursor.close = failing_close
        lease = SqlConnectionLease(raw_connection, 30)
        lease.cursor()
        lease.close()
        self.assertEqual(raw_connection.raw_cursor.close_count, 1)
        self.assertEqual(raw_connection.close_count, 1)

    def test_repeated_sql_connection_cycles_close_every_resource_once(self):
        connections = []
        autocommit_values = []

        def connect(_connection_string, *, autocommit, timeout):
            _ = timeout
            autocommit_values.append(autocommit)
            connection = _cleanup_support__RawConnection()
            connections.append(connection)
            return connection

        manager = SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])
        request = SqlConnectionRequest(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        with patch(
            "ost_visualizer.infrastructure.sql.connection_manager.pyodbc.connect",
            side_effect=connect,
        ):
            for _ in range(50):
                with manager.connection(request, autocommit=True) as lease:
                    with lease.cursor():
                        pass
        self.assertEqual(len(connections), 50)
        self.assertEqual(autocommit_values, [True] * 50)
        self.assertTrue(all(conn.close_count == 1 for conn in connections))
        self.assertTrue(all(conn.raw_cursor.close_count == 1 for conn in connections))


class ConnectionManagerDatabaseDescriptorTests(unittest.TestCase):
    def test_connection_request_repr_redacts_secret(self):
        request = SqlConnectionRequest(
            SqlServerDatabaseLocation(
                server="localhost",
                database="OSTV_TEST_123",
                authentication_mode=SqlAuthenticationMode.SQL_SERVER,
                username="test-user",
            ),
            password=secrets.token_urlsafe(24),
        )
        self.assertIn("password=<redacted>", repr(request))
        manager = SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])
        connection_string = manager.build_connection_string(request)
        self.assertIn("DRIVER={ODBC Driver 18 for SQL Server}", connection_string)
        self.assertIn("Encrypt=yes", connection_string)
        self.assertIn(f"PWD={{{request.password}}}", connection_string)
        self.assertIn("UID={test-user}", connection_string)
        self.assertNotIn("Trusted_Connection", connection_string)
        self.assertNotIn(request.password, repr(request))
        self.assertNotIn(request.password, repr(manager))

    def test_windows_authentication_and_read_only_intent_in_connection_string(self):
        manager = SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])
        request = SqlConnectionRequest(
            SqlServerDatabaseLocation(server="host,1433", database="DB"),
            read_only=True,
            database_override="Other}DB",
        )
        connection_string = manager.build_connection_string(request)
        self.assertIn("SERVER={tcp:host,1433}", connection_string)
        self.assertIn("DATABASE={Other}}DB}", connection_string)
        self.assertIn("ApplicationIntent=ReadOnly", connection_string)
        self.assertIn("Trusted_Connection=yes", connection_string)
        self.assertNotIn("PWD=", connection_string)

    def test_sql_authentication_without_password_is_rejected(self):
        manager = SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])
        request = SqlConnectionRequest(
            SqlServerDatabaseLocation(
                server="localhost",
                database="DB",
                authentication_mode=SqlAuthenticationMode.SQL_SERVER,
                username="test-user",
            )
        )
        with self.assertRaisesRegex(ValueError, "username and password"):
            manager.build_connection_string(request)

    def test_driver_17_is_not_an_accepted_schema_client(self):
        manager = SqlConnectionManager(drivers=["ODBC Driver 17 for SQL Server"])
        with self.assertRaisesRegex(SqlInfrastructureError, "Driver 18") as caught:
            _ = manager.driver
        self.assertEqual(caught.exception.details.code, SqlErrorCode.CONNECTION_FAILED)
        with self.assertRaises(SqlInfrastructureError):
            manager.build_connection_string(
                SqlConnectionRequest(
                    SqlServerDatabaseLocation(server="localhost", database="DB")
                )
            )

    def test_driver_18_is_selected_when_installed_alongside_older_drivers(self):
        manager = SqlConnectionManager(
            drivers=["ODBC Driver 17 for SQL Server", "ODBC Driver 18 for SQL Server"]
        )
        self.assertEqual(manager.driver, "ODBC Driver 18 for SQL Server")
