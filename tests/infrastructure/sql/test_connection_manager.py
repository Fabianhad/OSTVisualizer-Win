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
            raw.close.assert_called_once_with()


class ConnectionManagerSqlCleanupTests(unittest.TestCase):
    def test_sql_connection_lease_close_is_idempotent(self):
        raw_connection = _cleanup_support__RawConnection()
        lease = SqlConnectionLease(raw_connection, 30)
        lease.close()
        lease.close()
        self.assertEqual(raw_connection.close_count, 1)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            lease.cursor()

    def test_repeated_sql_connection_cycles_close_every_resource_once(self):
        connections = []

        def connect(_connection_string, *, autocommit, timeout):
            _ = autocommit, timeout
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
        self.assertNotIn(request.password, repr(manager))

    def test_driver_17_is_not_an_accepted_schema_client(self):
        manager = SqlConnectionManager(drivers=["ODBC Driver 17 for SQL Server"])
        with self.assertRaisesRegex(Exception, "Driver 18"):
            _ = manager.driver
