import contextlib
import os
import unittest
from unittest.mock import patch
import pyodbc

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.hierarchy_data import HierarchyFileEntry
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.reader_router import DatabaseProjectReader
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.schema_compatibility import MdbSchemaInspector
from ost_visualizer.infrastructure.sql.reader import SqlProjectReader
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.infrastructure.sql.write_schema import CurrentSqlWriteSchema
from tests.helpers.sql.cleanup_support import (
    _CredentialStore as _cleanup_support__CredentialStore,
)


class ReaderRouterSqlCleanupTests(unittest.TestCase):
    def test_database_reader_router_preserves_access_schema_and_error_contract(self):
        reader = DatabaseProjectReader(
            object(), DatabaseDescriptorRegistry(), _cleanup_support__CredentialStore()
        )
        observed = {}

        def parse_access(active_reader, locator):
            observed["locator"] = locator
            observed["schema"] = active_reader._schema(object())
            observed["raises_optional_read_errors"] = (
                active_reader._record_caught_read_error(RuntimeError("optional"))
            )
            return HierarchyFileEntry(file_path=locator), []

        with patch.object(
            MdbReader, "parse_file", autospec=True, side_effect=parse_access
        ):
            parsed = reader.parse_file("example.mdb")
        self.assertEqual(observed["locator"], "example.mdb")
        self.assertIsInstance(observed["schema"], MdbSchemaInspector)
        self.assertIs(observed["raises_optional_read_errors"], False)
        self.assertEqual(parsed, (HierarchyFileEntry(file_path="example.mdb"), []))
        self.assertIsNone(reader._active_backend.get())

    def test_database_reader_router_preserves_sql_schema_and_error_contract(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        reader = DatabaseProjectReader(
            object(), registry, _cleanup_support__CredentialStore()
        )
        observed = {}

        def parse_sql(active_reader, database_id):
            observed["database_id"] = database_id
            observed["schema"] = active_reader._schema(object())
            observed["raises_read_errors"] = active_reader._record_caught_read_error(
                RuntimeError("snapshot")
            )
            return HierarchyFileEntry(file_path=database_id), []

        with patch.object(
            SqlProjectReader, "parse_file", autospec=True, side_effect=parse_sql
        ):
            parsed = reader.parse_file(descriptor.database_id)
        self.assertEqual(observed["database_id"], descriptor.database_id)
        self.assertIsInstance(observed["schema"], CurrentSqlWriteSchema)
        self.assertIs(observed["raises_read_errors"], True)
        self.assertEqual(
            parsed, (HierarchyFileEntry(file_path=descriptor.database_id), [])
        )
        self.assertIsNone(reader._active_backend.get())

    def test_access_reader_router_keeps_backend_scope_for_outer_error_handler(self):
        original = pyodbc.Error("42S02", "optional Access table is missing")
        statements = []

        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc_value, _traceback):
                return False

            @staticmethod
            def execute(sql, *params):
                statements.append((sql, params))
                raise original

        class _Connection:
            @staticmethod
            def cursor():
                return _Cursor()

        class _AccessConnections:
            @contextlib.contextmanager
            def connection(self, _database_id, *, autocommit=False):
                self.autocommit = autocommit
                yield _Connection()

        connections = _AccessConnections()
        reader = DatabaseProjectReader(
            connections,
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
        )
        with patch.object(
            MdbReader,
            "_schema",
            return_value=CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema),
        ):
            self.assertEqual(reader.get_pages_with_takeoffs("example.mdb", "1"), set())
        self.assertEqual(
            statements,
            [
                (
                    "SELECT DISTINCT [BidPageUID] FROM [BidTakeoffs] "
                    "WHERE [BidUID] = ?",
                    ("1",),
                )
            ],
        )
        self.assertTrue(connections.autocommit)
        self.assertIsNone(reader._active_backend.get())

    def test_sql_reader_router_keeps_backend_scope_for_outer_error_handler(self):
        original = pyodbc.Error("08S01", "snapshot read failed")
        statements = []

        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc_value, _traceback):
                return False

            @staticmethod
            def execute(sql, *params):
                statements.append((sql, params))
                if "BidTakeoffs" in sql:
                    raise original

        class _Connection:
            def __init__(self):
                self.commits = 0
                self.rollbacks = 0

            @staticmethod
            def cursor():
                return _Cursor()

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        class _SqlConnections:
            def __init__(self):
                self.connection_value = _Connection()

            @contextlib.contextmanager
            def connection(self, _request, *, autocommit=False):
                self.autocommit = autocommit
                yield self.connection_value

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        reader = DatabaseProjectReader(
            object(), registry, _cleanup_support__CredentialStore()
        )
        connections = _SqlConnections()
        reader._sql_connections = connections
        with self.assertRaises(pyodbc.Error) as raised:
            reader.get_pages_with_takeoffs(descriptor.database_id, "1")
        self.assertIs(raised.exception, original)
        self.assertEqual(
            [sql for sql, _params in statements][-1],
            "SELECT DISTINCT [BidPageUID] FROM [BidTakeoffs] WHERE [BidUID] = ?",
        )
        self.assertFalse(connections.autocommit)
        self.assertEqual(connections.connection_value.commits, 1)
        self.assertEqual(connections.connection_value.rollbacks, 1)
        self.assertIsNone(reader._active_backend.get())

    def test_parse_file_requires_a_registered_sql_descriptor_and_resets_scope(self):
        registry = DatabaseDescriptorRegistry()
        reader = DatabaseProjectReader(
            object(), registry, _cleanup_support__CredentialStore()
        )
        with self.assertRaises(LookupError):
            reader.parse_file("unregistered-sql-id")
        self.assertIsNone(reader._active_backend.get())

        def failing_parse(_active_reader, _locator):
            raise RuntimeError("parse failed")

        with patch.object(
            MdbReader, "parse_file", autospec=True, side_effect=failing_parse
        ):
            with self.assertRaisesRegex(RuntimeError, "parse failed"):
                reader.parse_file("example.mdb")
        self.assertIsNone(reader._active_backend.get())

    def test_connection_lifecycle_is_routed_to_access_handles_only_for_access(self):
        class _AccessConnections:
            def __init__(self):
                self.calls = []

            def close(self):
                self.calls.append(("close",))

            def close_database(self, locator):
                self.calls.append(("close_database", locator))

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        connections = _AccessConnections()
        reader = DatabaseProjectReader(
            connections, registry, _cleanup_support__CredentialStore()
        )
        reader.close_connection(descriptor.database_id)
        reader.refresh_connection(descriptor.database_id)
        self.assertEqual(connections.calls, [])
        reader.close_connection("example.mdb")
        reader.refresh_connection("example.mdb")
        reader.close_connection()
        self.assertEqual(
            connections.calls,
            [
                ("close_database", "example.mdb"),
                ("close_database", "example.mdb"),
                ("close",),
            ],
        )

    def test_reader_hooks_require_an_active_backend_scope(self):
        reader = DatabaseProjectReader(
            object(),
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
        )
        with self.assertRaisesRegex(RuntimeError, "no active backend scope"):
            reader._schema(object())
        with self.assertRaisesRegex(RuntimeError, "no active backend scope"):
            reader._hydrates_bid_navigation_snapshots()
        with self.assertRaisesRegex(RuntimeError, "explicit locator"):
            reader._record_caught_read_error(RuntimeError("no scope"))
        self.assertFalse(
            reader._record_caught_read_error(RuntimeError("no scope"), "example.mdb")
        )


def _sql_descriptor_and_registry():
    registry = DatabaseDescriptorRegistry()
    descriptor = DatabaseDescriptor.for_sql_server(
        SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
        schema_version=SQL_SCHEMA_V1.version,
    )
    registry.register(descriptor)
    return registry, descriptor


class ReaderRouterBackendDispatchTests(unittest.TestCase):
    """Second pass: every routed hook is dispatched by backend, both ways."""

    def test_every_backend_divergent_member_is_overridden_by_the_router(self):
        # Python method resolution would pick SqlProjectReader's version for
        # an Access locator; every member the two backends resolve differently
        # must therefore be owned (and dispatched) by the router itself.
        def resolved(cls, name):
            member = getattr(cls, name, None)
            return getattr(member, "__func__", member)

        names = {
            name
            for cls in (MdbReader, SqlProjectReader)
            for name in dir(cls)
            if not (name.startswith("__") and name.endswith("__"))
        }
        divergent = {
            name
            for name in names
            if resolved(MdbReader, name) is not resolved(SqlProjectReader, name)
            and name in dir(MdbReader)
        }
        self.assertTrue(
            {
                "_connection",
                "_schema",
                "_record_caught_read_error",
                "_hydrates_bid_navigation_snapshots",
                "parse_file",
            }
            <= divergent
        )
        self.assertEqual(divergent - set(vars(DatabaseProjectReader)), set())

    def test_active_backend_scope_wins_over_the_current_registry(self):
        registry, descriptor = _sql_descriptor_and_registry()
        reader = DatabaseProjectReader(
            object(), registry, _cleanup_support__CredentialStore()
        )
        self.assertIs(reader._is_sql(descriptor.database_id), True)
        self.assertIs(reader._is_sql("example.mdb"), False)
        token = reader._active_backend.set(DatabaseBackend.ACCESS)
        try:
            # The backend resolved at the operation boundary is authoritative
            # for the whole operation, whatever the locator now resolves to.
            self.assertIs(reader._is_sql(descriptor.database_id), False)
            registry.unregister(descriptor.database_id)
        finally:
            reader._active_backend.reset(token)
        token = reader._active_backend.set(DatabaseBackend.SQL_SERVER)
        try:
            self.assertIs(reader._is_sql("example.mdb"), True)
            self.assertIs(reader._is_sql(descriptor.database_id), True)
        finally:
            reader._active_backend.reset(token)
        with self.assertRaises(LookupError):
            reader._is_sql(descriptor.database_id)

    def test_navigation_snapshot_hydration_is_a_sql_only_capability(self):
        registry, _descriptor = _sql_descriptor_and_registry()
        reader = DatabaseProjectReader(
            object(), registry, _cleanup_support__CredentialStore()
        )
        for backend, expected in (
            (DatabaseBackend.SQL_SERVER, True),
            (DatabaseBackend.ACCESS, False),
        ):
            token = reader._active_backend.set(backend)
            try:
                with self.subTest(backend=backend):
                    self.assertIs(reader._hydrates_bid_navigation_snapshots(), expected)
            finally:
                reader._active_backend.reset(token)

    def test_read_error_policy_receives_the_error_and_locator_from_the_router(self):
        registry, descriptor = _sql_descriptor_and_registry()
        reader = DatabaseProjectReader(
            object(), registry, _cleanup_support__CredentialStore()
        )
        failure = RuntimeError("optional table failed")
        for locator, selected, other, verdict in (
            ("example.mdb", MdbReader, SqlProjectReader, "access-verdict"),
            (descriptor.database_id, SqlProjectReader, MdbReader, "sql-verdict"),
        ):
            with self.subTest(locator=locator):
                with (
                    patch.object(
                        selected, "_record_caught_read_error", return_value=verdict
                    ) as chosen,
                    patch.object(
                        other,
                        "_record_caught_read_error",
                        side_effect=AssertionError("wrong backend policy"),
                    ) as rejected,
                ):
                    # Without a scope the explicit locator picks the backend...
                    self.assertEqual(
                        reader._record_caught_read_error(failure, locator), verdict
                    )
                    # ...and an active scope picks it with the locator unused.
                    token = reader._active_backend.set(reader._backend(locator))
                    try:
                        self.assertEqual(
                            reader._record_caught_read_error(failure), verdict
                        )
                    finally:
                        reader._active_backend.reset(token)
                self.assertEqual(
                    [call.args for call in chosen.call_args_list],
                    [(failure, locator), (failure, None)],
                )
                rejected.assert_not_called()

    def test_parse_file_returns_the_selected_backends_result_and_resets_scope(self):
        registry, descriptor = _sql_descriptor_and_registry()
        reader = DatabaseProjectReader(
            object(), registry, _cleanup_support__CredentialStore()
        )
        for locator, selected, other in (
            ("example.mdb", MdbReader, SqlProjectReader),
            (descriptor.database_id, SqlProjectReader, MdbReader),
        ):
            hierarchy, cdn_types = HierarchyFileEntry(file_path=locator), {"1": "Walls"}
            with self.subTest(locator=locator):
                with (
                    patch.object(
                        selected,
                        "parse_file",
                        autospec=True,
                        return_value=(hierarchy, cdn_types),
                    ) as chosen,
                    patch.object(
                        other,
                        "parse_file",
                        autospec=True,
                        side_effect=AssertionError("wrong backend parser"),
                    ),
                ):
                    result = reader.parse_file(locator)
                self.assertIs(result[0], hierarchy)
                self.assertIs(result[1], cdn_types)
                chosen.assert_called_once_with(reader, locator)
                self.assertIsNone(reader._active_backend.get())

    def test_sql_descriptor_lost_between_lookups_is_reported_not_parsed(self):
        _registry, descriptor = _sql_descriptor_and_registry()

        class _RacingRegistry:
            """Descriptor registered between parse_file's two registry lookups."""

            def __init__(self):
                self.lookups = 0

            def resolve(self, _locator):
                self.lookups += 1
                return None if self.lookups == 1 else descriptor

        reader = DatabaseProjectReader(
            object(), _RacingRegistry(), _cleanup_support__CredentialStore()
        )
        with patch.object(
            SqlProjectReader,
            "parse_file",
            autospec=True,
            side_effect=AssertionError("parsed without a stable descriptor"),
        ):
            with self.assertRaisesRegex(LookupError, "SQL Server database descriptor"):
                reader.parse_file(descriptor.database_id)
        self.assertIsNone(reader._active_backend.get())

    def test_routed_connection_uses_only_the_selected_backends_connection(self):
        registry, descriptor = _sql_descriptor_and_registry()
        events = []

        class _AccessConnections:
            @contextlib.contextmanager
            def connection(self, locator, *, autocommit=False):
                events.append(("access", locator, autocommit))
                yield "access-connection"

        reader = DatabaseProjectReader(
            _AccessConnections(), registry, _cleanup_support__CredentialStore()
        )

        @contextlib.contextmanager
        def sql_connection(active_reader, locator):
            events.append(("sql", locator, active_reader))
            yield "sql-lease"

        with patch.object(SqlProjectReader, "_connection", new=sql_connection):
            with reader._connection(descriptor.database_id) as lease:
                self.assertEqual(lease, "sql-lease")
                self.assertEqual(reader._current_backend(), DatabaseBackend.SQL_SERVER)
            self.assertIsNone(reader._active_backend.get())
            with reader._connection("example.mdb") as connection:
                self.assertEqual(connection, "access-connection")
                self.assertEqual(reader._current_backend(), DatabaseBackend.ACCESS)
            self.assertIsNone(reader._active_backend.get())
        # A completed SQL read must not fall through and also open Access.
        self.assertEqual(
            events,
            [
                ("sql", descriptor.database_id, reader),
                ("access", "example.mdb", True),
            ],
        )

    def test_routed_connection_resets_its_scope_when_the_body_fails(self):
        registry, descriptor = _sql_descriptor_and_registry()

        @contextlib.contextmanager
        def sql_connection(_active_reader, _locator):
            yield "sql-lease"

        reader = DatabaseProjectReader(
            object(), registry, _cleanup_support__CredentialStore()
        )
        with patch.object(SqlProjectReader, "_connection", new=sql_connection):
            with self.assertRaisesRegex(RuntimeError, "read failed"):
                with reader._connection(descriptor.database_id):
                    raise RuntimeError("read failed")
        self.assertIsNone(reader._active_backend.get())


from tests.helpers.sql.strict_sql_fakes import (  # noqa: E402
    Reply,
    StrictSqlServer,
    snapshot_transaction_rules,
    sql_server_error,
)


class _ForbiddenAccessConnections:
    def connection(self, *_args, **_kwargs):
        raise AssertionError("a SQL read opened an Access connection")

    def close(self):
        raise AssertionError("a SQL read closed Access handles")

    def close_database(self, _locator):
        raise AssertionError("a SQL read closed Access handles")


class ReaderRouterStrictSqlLeaseTests(unittest.TestCase):
    """Routed SQL reads against the strict pyodbc/T-SQL protocol model.
    The router, SqlProjectReader and SqlConnectionManager are real; only the
    pyodbc connection is the strict model (it enforces protocol rules and
    cleanup, never T-SQL semantics or live server behaviour).
    """

    def _router(self, server):
        registry, descriptor = _sql_descriptor_and_registry()
        reader = DatabaseProjectReader(
            _ForbiddenAccessConnections(),
            registry,
            _cleanup_support__CredentialStore(),
        )
        reader._sql_connections = server.manager()
        return reader, descriptor

    @staticmethod
    def _server():
        server = StrictSqlServer()
        snapshot_transaction_rules(server)
        server.on("SELECT 1", Reply.rows((1,)))
        return server

    def test_successful_routed_read_is_one_snapshot_lease_closed_afterwards(self):
        server = self._server()
        reader, descriptor = self._router(server)
        with server.patched():
            with reader._connection(descriptor.database_id) as lease:
                self.assertEqual(reader._current_backend(), DatabaseBackend.SQL_SERVER)
                with lease.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    self.assertEqual(cursor.fetchone(), (1,))
        self.assertIsNone(reader._active_backend.get())
        self.assertEqual(len(server.connections), 1)
        raw = server.connections[0]
        self.assertEqual(
            server.statements(1)[:3],
            [
                "SET TRANSACTION ISOLATION LEVEL SNAPSHOT",
                "BEGIN TRANSACTION",
                "SELECT 1",
            ],
        )
        self.assertEqual((raw.commits, raw.rollbacks), (2, 0))
        server.assert_everything_closed()

    def test_routed_read_failure_rolls_back_closes_and_restores_the_scope(self):
        for label, prepare in (
            ("body error", lambda server: None),
            (
                "rollback also fails",
                lambda server: server.fail(
                    "rollback", sql_server_error("08S01", "Communication link failure")
                ),
            ),
        ):
            with self.subTest(label=label):
                server = self._server()
                prepare(server)
                reader, descriptor = self._router(server)
                with server.patched():
                    with self.assertRaisesRegex(RuntimeError, "parse failed"):
                        with reader._connection(descriptor.database_id):
                            raise RuntimeError("parse failed")
                self.assertIsNone(reader._active_backend.get())
                raw = server.connections[0]
                self.assertEqual((raw.commits, raw.rollbacks), (1, 1))
                server.assert_everything_closed()

    def test_connection_lifecycle_calls_never_reach_a_sql_database(self):
        server = self._server()
        reader, descriptor = self._router(server)
        with server.patched():
            reader.close_connection(descriptor.database_id)
            reader.refresh_connection(descriptor.database_id)
        self.assertEqual(server.connections, [])
