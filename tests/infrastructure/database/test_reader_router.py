import contextlib
import os
import unittest
from unittest.mock import patch
import pyodbc

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
    credential_target_for,
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

    def test_access_reader_router_keeps_backend_scope_for_outer_error_handler(self):
        original = pyodbc.Error("42S02", "optional Access table is missing")

        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc_value, _traceback):
                return False

            @staticmethod
            def execute(_sql, *_params):
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

        reader = DatabaseProjectReader(
            _AccessConnections(),
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
        )
        with patch.object(
            MdbReader,
            "_schema",
            return_value=CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema),
        ):
            self.assertEqual(reader.get_pages_with_takeoffs("example.mdb", "1"), set())

    def test_sql_reader_router_keeps_backend_scope_for_outer_error_handler(self):
        original = pyodbc.Error("08S01", "snapshot read failed")

        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc_value, _traceback):
                return False

            @staticmethod
            def execute(_sql, *_params):
                raise original

        class _Connection:
            @staticmethod
            def cursor():
                return _Cursor()

            @staticmethod
            def rollback():
                pass

        class _SqlConnections:
            @contextlib.contextmanager
            def connection(self, _request, *, autocommit=False):
                self.autocommit = autocommit
                yield _Connection()

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        reader = DatabaseProjectReader(
            object(), registry, _cleanup_support__CredentialStore()
        )
        reader._sql_connections = _SqlConnections()
        with self.assertRaises(pyodbc.Error) as raised:
            reader.get_pages_with_takeoffs(descriptor.database_id, "1")
        self.assertIs(raised.exception, original)
