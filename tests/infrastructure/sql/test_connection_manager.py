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


from tests.helpers.sql.strict_sql_fakes import (  # noqa: E402
    MAX_PARAMETERS,
    Reply,
    StrictSqlServer,
    StrictSqlViolation,
    applock_rules,
    snapshot_transaction_rules,
    sql_server_error,
)
from ost_visualizer.infrastructure.sql.connection_manager import (  # noqa: E402
    begin_snapshot_transaction,
)


def _strict_request(**location):
    return SqlConnectionRequest(
        SqlServerDatabaseLocation(server="localhost", database="TEST", **location)
    )


class StrictSqlFakeContractTests(unittest.TestCase):
    """The strict pyodbc stand-in must itself refuse what a real server refuses.
    Every other strict test in the SQL suite relies on these rules, so each is
    pinned here against the pyodbc/T-SQL behaviour it models. Nothing in this
    class proves server behaviour; it proves the fake is not more permissive
    than the documented driver behaviour it claims to model.
    """

    def _open(self, server=None, autocommit=False):
        server = server or StrictSqlServer()
        server.on("SELECT 1", Reply.rows((1,)))
        server.on("SELECT TWO", Reply.sets([(1,)], [(2,)], columns=("a",)))
        server.on("DML", Reply.dml(3))
        manager = server.manager()
        patcher = server.patched()
        patcher.__enter__()
        self.addCleanup(patcher.__exit__, None, None, None)
        context = manager.connection(_strict_request(), autocommit=autocommit)
        lease = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        return server, lease

    def test_closed_cursor_and_closed_connection_raise_like_pyodbc(self):
        server, lease = self._open()
        cursor = lease.cursor()
        cursor.close()
        for label, use in (
            ("execute", lambda: cursor.execute("SELECT 1")),
            ("fetchone", cursor.fetchone),
            ("fetchall", cursor.fetchall),
            ("rowcount", lambda: cursor.rowcount),
        ):
            with self.subTest(use=label):
                with self.assertRaisesRegex(pyodbc.ProgrammingError, "closed cursor"):
                    use()
        raw = server.connections[0]
        raw.close()
        with self.assertRaisesRegex(pyodbc.ProgrammingError, "closed connection"):
            raw.cursor()
        with self.assertRaisesRegex(pyodbc.ProgrammingError, "closed connection"):
            raw.commit()

    def test_parameter_markers_must_match_and_a_request_carries_at_most_2100(self):
        server = StrictSqlServer()
        server.on("IN (", Reply.dml(0))
        server, lease = self._open(server)
        cursor = lease.cursor()

        def run(count, supplied=None):
            sql = (
                "DELETE FROM [BidTakeoffs] WHERE [UID] IN ("
                + ",".join("?" * count)
                + ")"
            )
            values = tuple(range(count if supplied is None else supplied))
            return cursor.execute(sql, *values)

        # exactly one below, at and one above the driver limit
        run(MAX_PARAMETERS - 1)
        run(MAX_PARAMETERS)
        with self.assertRaises(pyodbc.Error) as over:
            run(MAX_PARAMETERS + 1)
        self.assertEqual(over.exception.args[0], "07002")
        self.assertIn("2100", over.exception.args[1])
        # a marker/parameter count mismatch is a driver error in both directions
        with self.assertRaisesRegex(
            pyodbc.ProgrammingError, "2 parameter markers, but 1 parameters"
        ):
            run(2, supplied=1)
        with self.assertRaisesRegex(
            pyodbc.ProgrammingError, "2 parameter markers, but 3 parameters"
        ):
            run(2, supplied=3)
        # '?' inside literals, comments and bracketed names is not a marker
        cursor.execute(
            "DELETE FROM [BidTakeoffs] WHERE [Name]=N'?' -- ?\n AND [UID] IN (?)", 1
        )
        # one sequence argument is the parameter list: execute(sql, [a, b])
        cursor.execute("DELETE FROM [BidTakeoffs] WHERE [UID] IN (?, ?)", [1, 2])

    def test_nocount_is_session_scoped_and_rowcount_reflects_the_last_statement(self):
        server, lease = self._open()
        cursor = lease.cursor()
        cursor.execute("DML")
        self.assertEqual(cursor.rowcount, 3)
        cursor.execute("SELECT 1")
        self.assertEqual(cursor.rowcount, -1)
        cursor.execute("SET NOCOUNT ON; DML")
        self.assertEqual(cursor.rowcount, -1)
        # SET NOCOUNT persists for the connection, not just for the batch
        cursor.execute("DML")
        self.assertEqual(cursor.rowcount, -1)
        cursor.execute("SET NOCOUNT OFF; DML")
        self.assertEqual(cursor.rowcount, 3)

    def test_result_sets_are_consumed_in_order_and_unfetched_rows_block_the_connection(
        self,
    ):
        server, lease = self._open()
        cursor = lease.cursor()
        with self.assertRaisesRegex(pyodbc.ProgrammingError, "No results"):
            cursor.fetchone()
        cursor.execute("DML")
        with self.assertRaisesRegex(pyodbc.ProgrammingError, "No results"):
            cursor.fetchall()
        cursor.execute("SELECT TWO")
        self.assertEqual(cursor.description[0][0], "a")
        self.assertEqual(cursor.fetchone(), (1,))
        self.assertEqual(cursor.fetchall(), [])
        self.assertIsNone(cursor.fetchone())
        self.assertTrue(cursor.nextset())
        self.assertEqual(cursor.fetchall(), [(2,)])
        self.assertFalse(cursor.nextset())
        with self.assertRaisesRegex(pyodbc.ProgrammingError, "No results"):
            cursor.fetchone()
        # a second cursor cannot run while rows of the first are unfetched
        cursor.execute("SELECT TWO")
        other = lease.cursor()
        with self.assertRaisesRegex(pyodbc.Error, "Connection is busy"):
            other.execute("SELECT 1")
        cursor.fetchall()
        cursor.nextset()
        cursor.fetchall()
        other.execute("SELECT 1")
        self.assertEqual(other.fetchone(), (1,))

    def test_database_ddl_and_transaction_locks_follow_the_connection_mode(self):
        server = StrictSqlServer()
        server.on("DATABASE", Reply())
        server.on("sp_getapplock", Reply.rows((0,)))
        server, lease = self._open(server, autocommit=False)
        cursor = lease.cursor()
        with self.assertRaises(pyodbc.Error) as ddl:
            cursor.execute("ALTER DATABASE CURRENT SET ALLOW_SNAPSHOT_ISOLATION ON")
        self.assertIn("(226)", ddl.exception.args[1])
        with self.assertRaises(pyodbc.Error):
            cursor.execute("CREATE DATABASE [X]")
        cursor.execute(
            "EXEC sys.sp_getapplock @Resource=N'r', @LockOwner=N'Transaction'"
        )
        auto_server = StrictSqlServer()
        auto_server.on("DATABASE", Reply())
        auto_server.on("sp_getapplock", Reply.rows((0,)))
        _server, auto_lease = self._open(auto_server, autocommit=True)
        auto_cursor = auto_lease.cursor()
        auto_cursor.execute("ALTER DATABASE CURRENT SET ALLOW_SNAPSHOT_ISOLATION ON")
        with self.assertRaisesRegex(StrictSqlViolation, "autocommit"):
            auto_cursor.execute(
                "EXEC sys.sp_getapplock @Resource=N'r', @LockOwner=N'Transaction'"
            )
        # the session-owned lock is the autocommit form and stays legal
        auto_cursor.execute(
            "EXEC sys.sp_getapplock @Resource=N'r', @LockOwner=N'Session'"
        )

    def test_snapshot_isolation_cannot_be_applied_after_the_transaction_read_data(
        self,
    ):
        server = StrictSqlServer()
        snapshot_transaction_rules(server)
        server, lease = self._open(server)
        cursor = lease.cursor()
        cursor.execute("SELECT 1")
        cursor.execute("SET TRANSACTION ISOLATION LEVEL SNAPSHOT")
        with self.assertRaises(pyodbc.Error) as late:
            cursor.execute("SELECT 1")
        self.assertIn("(3951)", late.exception.args[1])
        lease.rollback()
        # after the transaction ended the same sequence is legal
        cursor.execute("SET TRANSACTION ISOLATION LEVEL SNAPSHOT")
        cursor.execute("BEGIN TRANSACTION")
        cursor.execute("SELECT 1")
        # and a database without ALLOW_SNAPSHOT_ISOLATION refuses the first read
        disabled = StrictSqlServer(snapshot_enabled=False)
        snapshot_transaction_rules(disabled)
        _server, lease2 = self._open(disabled)
        cursor2 = lease2.cursor()
        cursor2.execute("SET TRANSACTION ISOLATION LEVEL SNAPSHOT")
        cursor2.execute("BEGIN TRANSACTION")
        with self.assertRaises(pyodbc.Error) as disabled_error:
            cursor2.execute("SELECT 1")
        self.assertIn("(3952)", disabled_error.exception.args[1])

    def test_unscripted_statements_and_unknown_catalog_names_are_rejected(self):
        server = StrictSqlServer()
        server.on("INSERT INTO", Reply.dml(1))
        server.on("SELECT", Reply.rows((1,)))
        server, lease = self._open(server)
        cursor = lease.cursor()
        with self.assertRaisesRegex(StrictSqlViolation, "unscripted"):
            cursor.execute("TRUNCATE TABLE [dbo].[Bids]")
        with self.assertRaises(pyodbc.Error) as table:
            cursor.execute("INSERT INTO [dbo].[NoSuchTable] ([A]) VALUES (?)", 1)
        self.assertEqual(table.exception.args[0], "42S02")
        with self.assertRaises(pyodbc.Error) as column:
            cursor.execute(
                "INSERT INTO [dbo].[BidProjects] ([NoSuchColumn]) VALUES (?)", 1
            )
        self.assertEqual(column.exception.args[0], "42S22")
        with self.assertRaises(pyodbc.Error):
            cursor.execute("SELECT [UID] FROM [NoSuchTable]")
        with self.assertRaises(pyodbc.Error):
            # an ostv table is not visible through the dbo default schema
            cursor.execute("SELECT [SessionId] FROM [Sessions]")
        cursor.execute("INSERT INTO [dbo].[BidProjects] ([Name]) VALUES (?)", "x")
        cursor.execute("INSERT INTO [ostv].[Sessions] ([SessionId]) VALUES (?)", "x")
        cursor.execute("SELECT [UID] FROM [BidProjects]")
        # identifiers are case-insensitive under the default collation
        cursor.execute("INSERT INTO [DBO].[bidprojects] ([name]) VALUES (?)", "x")

    def test_application_locks_conflict_across_connections_and_release_at_transaction_end(
        self,
    ):
        server = StrictSqlServer()
        applock_rules(server)
        manager = server.manager()
        statement = (
            "DECLARE @result int; EXEC @result=sys.sp_getapplock @Resource=?, "
            "@LockMode=N'Exclusive', @LockOwner=N'Transaction', "
            "@LockTimeout=10000; SELECT @result"
        )
        with server.patched():
            with manager.connection(_strict_request()) as first:
                with first.cursor() as cursor:
                    cursor.execute(statement, "OSTV:takeoff:1")
                    self.assertEqual(cursor.fetchone(), (0,))
                with manager.connection(_strict_request()) as second:
                    with second.cursor() as cursor:
                        cursor.execute(statement, "OSTV:takeoff:1")
                        # timeout (-1): never granted while the first transaction lives
                        self.assertEqual(cursor.fetchone(), (-1,))
                first.commit()
                with manager.connection(_strict_request()) as third:
                    with third.cursor() as cursor:
                        cursor.execute(statement, "OSTV:takeoff:1")
                        self.assertEqual(cursor.fetchone(), (0,))
                    third.rollback()
                    self.assertEqual(server.applocks.holders("OSTV:takeoff:1"), [])
        self.assertEqual(
            [(number, code) for number, _res, _mode, code in server.applocks.log],
            [(1, 0), (2, -1), (3, 0)],
        )

    def test_injected_faults_surface_at_the_driver_boundary(self):
        server, lease = self._open()
        server.fail("commit", sql_server_error("08S01", "Communication link failure"))
        with self.assertRaises(pyodbc.Error):
            lease.commit()
        server.fail("rollback", sql_server_error("08S01", "Communication link failure"))
        with self.assertRaises(pyodbc.Error):
            lease.rollback()
        raw = server.connections[0]
        self.assertEqual((raw.commits, raw.rollbacks), (1, 1))


class ConnectionManagerStrictLifecycleTests(unittest.TestCase):
    """Per-operation leases against the strict pyodbc model."""

    @staticmethod
    def _server():
        server = StrictSqlServer()
        snapshot_transaction_rules(server)
        server.on("SELECT 1", Reply.rows((1,)))
        return server

    def test_cursor_closes_before_connection_on_success_and_on_body_error(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                server = self._server()
                manager = server.manager()
                with server.patched():
                    try:
                        with manager.connection(_strict_request()) as lease:
                            with lease.cursor() as cursor:
                                cursor.execute("SELECT 1")
                            lease.cursor()
                            if fail:
                                raise ValueError("boom")
                    except ValueError:
                        self.assertTrue(fail)
                server.assert_everything_closed()
                self.assertEqual(
                    server.event_kinds(1),
                    [
                        "cursor_open",
                        "execute",
                        "cursor_close",
                        "cursor_open",
                        "cursor_close",
                        "close",
                    ],
                )

    def test_lease_closes_the_connection_even_when_a_cursor_close_fails_unexpectedly(
        self,
    ):
        server = self._server()
        manager = server.manager()
        server.fail("cursor_close", RuntimeError("cursor close exploded"))
        with server.patched():
            with self.assertRaisesRegex(RuntimeError, "cursor close exploded"):
                with manager.connection(_strict_request()) as lease:
                    lease.cursor()
        raw = server.connections[0]
        self.assertTrue(raw.closed, "the physical connection must never leak")

    def test_driver_errors_inside_the_block_are_classified_and_never_leak(self):
        cases = (
            (
                sql_server_error("08S01", "Communication link failure"),
                SqlErrorCode.CONNECTION_FAILED,
            ),
            (sql_server_error("HYT00", "Query timeout expired"), SqlErrorCode.TIMEOUT),
            (
                sql_server_error(
                    "23000", "Violation of PRIMARY KEY constraint 'PK_x'", 2627
                ),
                SqlErrorCode.CONSTRAINT_FAILED,
            ),
            (
                sql_server_error(
                    "23000", "The INSERT statement conflicted with the FOREIGN KEY", 547
                ),
                SqlErrorCode.CONSTRAINT_FAILED,
            ),
        )
        for error, code in cases:
            with self.subTest(state=error.args[0], text=error.args[1][:40]):
                server = self._server()
                manager = server.manager()

                def fail(_call, error=error):
                    raise error

                server.on("FAIL", fail)
                with server.patched():
                    with self.assertRaises(SqlInfrastructureError) as caught:
                        with manager.connection(_strict_request()) as lease:
                            with lease.cursor() as cursor:
                                cursor.execute("FAIL")
                self.assertEqual(caught.exception.details.code, code)
                self.assertIsNone(caught.exception.__cause__)
                server.assert_everything_closed()

    def test_failed_connect_never_opens_a_connection_and_hides_the_connection_string(
        self,
    ):
        secret = secrets.token_urlsafe(16)
        server = StrictSqlServer()
        server.connect_error = pyodbc.Error(
            "28000", f"Login failed for user 'u' (18456) PWD={secret}"
        )
        manager = server.manager()
        location = SqlServerDatabaseLocation(
            server="localhost",
            database="TEST",
            authentication_mode=SqlAuthenticationMode.SQL_SERVER,
            username="u",
        )
        request = SqlConnectionRequest(location, password=secret)
        with server.patched():
            with self.assertRaises(SqlInfrastructureError) as caught:
                with manager.connection(request):
                    self.fail("no lease may be yielded")
        self.assertEqual(server.connections, [])
        self.assertIn(secret, server.connect_calls[0]["connection_string"])
        error = caught.exception
        self.assertEqual(error.details.code, SqlErrorCode.AUTHENTICATION_FAILED)
        self.assertNotIn(secret, str(error))
        self.assertNotIn(secret, repr(error))
        self.assertNotIn(secret, repr(error.details))
        self.assertNotIn(secret, repr(request))

    def test_snapshot_transaction_ends_the_set_statement_before_begin_and_closes_cursor(
        self,
    ):
        server = self._server()
        manager = server.manager()
        with server.patched():
            with manager.connection(_strict_request()) as lease:
                begin_snapshot_transaction(lease)
                with lease.cursor() as cursor:
                    cursor.execute("SELECT 1")
                lease.commit()
        self.assertEqual(
            server.event_kinds(1),
            [
                "cursor_open",
                "execute",  # SET TRANSACTION ISOLATION LEVEL SNAPSHOT
                "commit",
                "execute",  # BEGIN TRANSACTION
                "cursor_close",
                "cursor_open",
                "execute",  # the read inside the snapshot transaction
                "cursor_close",
                "commit",
                "close",
            ],
        )
        self.assertEqual(
            server.statements(1)[:2],
            ["SET TRANSACTION ISOLATION LEVEL SNAPSHOT", "BEGIN TRANSACTION"],
        )
        server.assert_everything_closed()

    def test_escaped_lease_and_cursor_are_unusable_after_the_operation(self):
        server = self._server()
        manager = server.manager()
        with server.patched():
            with manager.connection(_strict_request()) as first:
                cursor = first.cursor()
            with manager.connection(_strict_request()) as second:
                self.assertIsNot(first, second)
        self.assertEqual(len(server.connections), 2)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            first.cursor()
        with self.assertRaisesRegex(pyodbc.ProgrammingError, "closed cursor"):
            cursor.execute("SELECT 1")

    def test_concurrent_operations_each_get_their_own_physical_connection(self):
        import threading

        server = self._server()
        manager = server.manager()
        barrier = threading.Barrier(2)
        seen = []
        errors = []

        def work():
            try:
                with manager.connection(_strict_request()) as lease:
                    barrier.wait(5)
                    with lease.cursor() as cursor:
                        cursor.execute("SELECT 1")
                    seen.append(lease)
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)

        with server.patched():
            threads = [threading.Thread(target=work) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
        self.assertEqual(errors, [])
        self.assertEqual(len(seen), 2)
        self.assertIsNot(seen[0], seen[1])
        self.assertEqual(len(server.connections), 2)
        server.assert_everything_closed()


class ConnectionManagerBookkeepingTests(unittest.TestCase):
    """Survivors of the second-pass mutation sweep over connection_manager.py."""

    MANAGER_DRIVERS = ["ODBC Driver 18 for SQL Server"]

    def _string(self, **kwargs):
        location = kwargs.pop("location", None) or SqlServerDatabaseLocation(
            server="localhost", database="DB"
        )
        manager = SqlConnectionManager(drivers=self.MANAGER_DRIVERS)
        return manager.build_connection_string(SqlConnectionRequest(location, **kwargs))

    def test_connection_request_is_immutable_and_defaults_to_a_read_write_windows_intent(
        self,
    ):
        import dataclasses

        request = SqlConnectionRequest(
            SqlServerDatabaseLocation(server="localhost", database="DB")
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            request.password = "changed"
        self.assertEqual(request.password, "")
        self.assertIsNone(request.database_override)
        self.assertFalse(request.read_only)
        self.assertNotIn("ApplicationIntent", self._string())
        self.assertIn("ApplicationIntent=ReadOnly;", self._string(read_only=True))

    def test_server_names_get_a_tcp_prefix_only_for_host_port_forms(self):
        for server, expected in (
            ("host", "SERVER={host};"),
            ("host,1433", "SERVER={tcp:host,1433};"),
            ("tcp:host,1433", "SERVER={tcp:host,1433};"),
            ("TCP:host,1433", "SERVER={TCP:host,1433};"),
            ("  host,1433  ", "SERVER={tcp:host,1433};"),
            (".\\SQLEXPRESS", "SERVER={.\\SQLEXPRESS};"),
        ):
            with self.subTest(server=server):
                text = self._string(
                    location=SqlServerDatabaseLocation(server=server, database="DB")
                )
                self.assertIn(expected, text)
        with self.assertRaisesRegex(ValueError, "name is required"):
            self._string(location=SqlServerDatabaseLocation(server="  ", database="DB"))

    def test_database_defaults_to_master_and_an_override_wins(self):
        blank = SqlServerDatabaseLocation(server="localhost", database="")
        self.assertIn("DATABASE={master};", self._string(location=blank))
        self.assertIn(
            "DATABASE={Other};", self._string(location=blank, database_override="Other")
        )
        named = SqlServerDatabaseLocation(server="localhost", database="Named")
        self.assertIn("DATABASE={Named};", self._string(location=named))
        self.assertIn(
            "DATABASE={master};",
            self._string(location=named, database_override="master"),
        )

    def test_sql_authentication_needs_both_username_and_password(self):
        for username, password in (("", "secret"), ("user", ""), ("", "")):
            with self.subTest(username=username, password=bool(password)):
                location = SqlServerDatabaseLocation(
                    server="localhost",
                    database="DB",
                    authentication_mode=SqlAuthenticationMode.SQL_SERVER,
                    username=username,
                )
                with self.assertRaisesRegex(ValueError, "username and password"):
                    self._string(location=location, password=password)
        with self.assertRaisesRegex(ValueError, "null character"):
            self._string(
                location=SqlServerDatabaseLocation(
                    server="localhost",
                    database="DB",
                    authentication_mode=SqlAuthenticationMode.SQL_SERVER,
                    username="user",
                ),
                password="pass\x00word",
            )

    def test_lease_delegates_commit_rollback_and_getinfo_and_forgets_closed_cursors(
        self,
    ):
        server = StrictSqlServer()
        server.on("SELECT 1", Reply.rows((1,)))
        manager = server.manager()
        with server.patched():
            with manager.connection(_strict_request()) as lease:
                raw = server.connections[0]
                self.assertEqual(lease.getinfo(2), raw.getinfo(2))
                lease.commit()
                lease.rollback()
                self.assertEqual((raw.commits, raw.rollbacks), (1, 1))
                cursors = [lease.cursor() for _ in range(3)]
                self.assertEqual(len(lease._cursors), 3)
                cursors[1].close()
                self.assertEqual(lease._cursors, [cursors[0], cursors[2]])
                cursors[0].close()
                cursors[2].close()
                # a long-lived lease does not accumulate closed cursor leases
                self.assertEqual(lease._cursors, [])
                for _ in range(500):
                    with lease.cursor() as cursor:
                        cursor.execute("SELECT 1")
                self.assertEqual(lease._cursors, [])
                dangling = lease.cursor()
            self.assertTrue(raw.closed)
            self.assertTrue(dangling._closed)
            self.assertEqual(lease._cursors, [])

    def test_a_failure_configuring_a_fresh_connection_still_closes_it(self):
        class _TimeoutRejectingConnection(_cleanup_support__RawConnection):
            @property
            def timeout(self):
                return 0

            @timeout.setter
            def timeout(self, _value):
                raise ValueError("unsupported command timeout")

        raw = _TimeoutRejectingConnection()
        manager = SqlConnectionManager(drivers=self.MANAGER_DRIVERS)
        with patch(
            "ost_visualizer.infrastructure.sql.connection_manager.pyodbc.connect",
            return_value=raw,
        ):
            with self.assertRaisesRegex(ValueError, "unsupported command timeout"):
                with manager.connection(_strict_request()):
                    self.fail("no lease may be yielded")
        self.assertEqual(raw.close_count, 1)


class DescriptorConnectionFactoryTests(unittest.TestCase):
    """Survivors of the second-pass mutation sweep over descriptor_connection.py."""

    def _factory(self, passwords, *, authentication=SqlAuthenticationMode.SQL_SERVER):
        from ost_visualizer.infrastructure.database.descriptor_registry import (
            DatabaseDescriptorRegistry,
        )
        from ost_visualizer.infrastructure.sql.descriptor_connection import (
            SqlDescriptorConnectionFactory,
        )

        class _Store:
            def __init__(self, stored):
                self.stored = stored
                self.reads = []

            def read_password(self, target):
                self.reads.append(target)
                return self.stored

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(
                server="localhost",
                database="DB",
                authentication_mode=authentication,
                username=(
                    "user" if authentication == SqlAuthenticationMode.SQL_SERVER else ""
                ),
            ),
            schema_version=1,
        )
        registry.register(descriptor)
        store = _Store(passwords)
        return (
            SqlDescriptorConnectionFactory(registry, store),
            store,
            descriptor,
            registry,
        )

    def test_a_stored_password_is_read_by_database_target_and_stays_out_of_the_repr(
        self,
    ):
        secret = secrets.token_urlsafe(18)
        factory, store, descriptor, _registry = self._factory(secret)
        request = factory.request(descriptor.database_id, read_only=True)
        self.assertEqual(request.password, secret)
        self.assertTrue(request.read_only)
        self.assertEqual(request.location, descriptor.sql_location)
        self.assertEqual(store.reads, [credential_target_for(descriptor.database_id)])
        self.assertNotIn(secret, repr(request))
        self.assertFalse(
            factory.request(descriptor.database_id, read_only=False).read_only
        )

    def test_missing_or_empty_stored_passwords_are_a_credential_error(self):
        for stored in (None, ""):
            with self.subTest(stored=stored):
                factory, _store, descriptor, _registry = self._factory(stored)
                with self.assertRaises(SqlInfrastructureError) as raised:
                    factory.request(descriptor.database_id, read_only=False)
                self.assertEqual(
                    raised.exception.details.code, SqlErrorCode.CREDENTIAL_MISSING
                )
                self.assertTrue(raised.exception.credential_required)
        # a whitespace password is a real (if unusual) password
        factory, _store, descriptor, _registry = self._factory(" ")
        self.assertEqual(
            factory.request(descriptor.database_id, read_only=False).password, " "
        )

    def test_windows_authentication_never_reads_the_credential_store(self):
        factory, store, descriptor, _registry = self._factory(
            "never-read", authentication=SqlAuthenticationMode.WINDOWS
        )
        request = factory.request(descriptor.database_id, read_only=False)
        self.assertEqual(request.password, "")
        self.assertEqual(store.reads, [])

    def test_unknown_and_access_descriptors_are_not_sql_connections(self):
        factory, _store, _descriptor, registry = self._factory("secret")
        access = DatabaseDescriptor.for_access("C:\\data\\project.mdb")
        registry.register(access)
        for database_id in ("missing-id", access.database_id):
            with self.subTest(database_id=database_id):
                with self.assertRaises(SqlInfrastructureError) as raised:
                    factory.request(database_id, read_only=False)
                self.assertEqual(
                    raised.exception.details.code, SqlErrorCode.DATABASE_MISSING
                )


class ConnectionManagerTransactionConflictPinTests(unittest.TestCase):
    """Decision D12 (pin): SqlConnectionManager only classifies deadlock victim
    (1205), lock timeout (1222) and snapshot update conflict (3960); it never
    retries a connect, a statement or a commit, and it never issues a commit or
    rollback of its own (closing the connection abandons the transaction).
    Strict fake: it injects the driver exception, it does not model the server
    conditions that raise it.
    """

    ERRORS = (
        sql_server_error(
            "40001",
            "Transaction (Process ID 55) was deadlocked on lock resources with "
            "another process and has been chosen as the deadlock victim. Rerun "
            "the transaction.",
            1205,
        ),
        sql_server_error("42000", "Lock request time out period exceeded.", 1222),
        sql_server_error(
            "42000",
            "Snapshot isolation transaction aborted due to update conflict. You "
            "cannot use snapshot isolation to access table 'dbo.Bids' directly or "
            "indirectly in database 'TEST' to update, delete, or insert the row "
            "that has been modified or deleted by another transaction.",
            3960,
        ),
    )

    def _assert_classified_retryable(self, raised):
        error = raised.exception
        self.assertEqual(error.details.code, SqlErrorCode.UNKNOWN)
        self.assertIsNone(error.details.native_code)
        self.assertTrue(error.retryable)
        self.assertFalse(error.read_only_required)
        self.assertFalse(error.credential_required)
        self.assertFalse(error.session_expired)
        self.assertIsNone(error.__cause__)

    def test_statement_error_is_classified_once_without_retry_commit_or_rollback(self):
        for error in self.ERRORS:
            with self.subTest(native=error.args[1][-30:]):
                server = StrictSqlServer()
                calls = []

                def fail(_call, error=error):
                    calls.append("DML")
                    raise error

                server.on("UPDATE DML", fail)
                manager = server.manager()
                with server.patched():
                    with self.assertRaises(SqlInfrastructureError) as raised:
                        with manager.connection(_strict_request()) as lease:
                            with lease.cursor() as cursor:
                                cursor.execute("UPDATE DML")
                self._assert_classified_retryable(raised)
                self.assertEqual(calls, ["DML"])
                self.assertEqual(len(server.connect_calls), 1)
                raw = server.connections[0]
                self.assertEqual((raw.commits, raw.rollbacks), (0, 0))
                self.assertEqual(
                    server.event_kinds(1),
                    ["cursor_open", "execute", "cursor_close", "close"],
                )
                server.assert_everything_closed()

    def test_commit_error_is_classified_after_one_commit_and_never_retried(self):
        for error in self.ERRORS:
            for committed in (False, True):
                with self.subTest(native=error.args[1][-30:], committed=committed):
                    server = StrictSqlServer()
                    server.fail("commit", error, committed=committed)
                    manager = server.manager()
                    with server.patched():
                        with self.assertRaises(SqlInfrastructureError) as raised:
                            with manager.connection(_strict_request()) as lease:
                                lease.commit()
                    self._assert_classified_retryable(raised)
                    self.assertEqual(len(server.connect_calls), 1)
                    raw = server.connections[0]
                    self.assertEqual((raw.commits, raw.rollbacks), (1, 0))
                    self.assertEqual(server.event_kinds(1), ["commit", "close"])
                    server.assert_everything_closed()

    def test_connect_error_of_the_same_kind_is_not_retried_either(self):
        for error in self.ERRORS:
            with self.subTest(native=error.args[1][-30:]):
                server = StrictSqlServer()
                server.connect_error = error
                manager = server.manager()
                with server.patched():
                    with self.assertRaises(SqlInfrastructureError) as raised:
                        with manager.connection(_strict_request()):
                            self.fail("no lease may be yielded")
                self._assert_classified_retryable(raised)
                self.assertEqual(len(server.connect_calls), 1)
                self.assertEqual(server.connections, [])
