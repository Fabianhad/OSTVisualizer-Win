import contextlib
import os
import unittest
from unittest.mock import patch
import pyodbc

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.database_descriptor import (
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
            reader.parse_file("example.mdb")
        self.assertEqual(observed["locator"], "example.mdb")
        self.assertIsInstance(observed["schema"], MdbSchemaInspector)
        self.assertFalse(observed["raises_optional_read_errors"])
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
            reader.parse_file(descriptor.database_id)
        self.assertEqual(observed["database_id"], descriptor.database_id)
        self.assertIsInstance(observed["schema"], CurrentSqlWriteSchema)
        self.assertTrue(observed["raises_read_errors"])
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
