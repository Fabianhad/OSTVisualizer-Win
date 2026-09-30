import contextlib
import logging
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import pyodbc
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
    credential_target_for,
)
from ost_visualizer.domain.entities.hierarchy_data import HierarchyFileEntry
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.sql.client_permissions import (
    SQL_CLIENT_DATABASE_ROLES,
    SQL_CLIENT_DIRECT_WRITE_TABLES,
    _sql_integer_values_match,
    apply_sql_client_permissions,
)
from ost_visualizer.infrastructure.sql.reader import SqlProjectReader
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.infrastructure.sql.schema_inspector import (
    SqlSchemaInspector,
    SqlSchemaInventory,
)
from ost_visualizer.infrastructure.sql.write_schema import CurrentSqlWriteSchema
from tests.helpers.sql.cleanup_support import (
    _CredentialStore as _cleanup_support__CredentialStore,
    _InspectionCursor as _cleanup_support__InspectionCursor,
    _InspectionLease as _cleanup_support__InspectionLease,
    _InspectionManager as _cleanup_support__InspectionManager,
    _canonical_writer_permission_snapshot as _cleanup_support__canonical_writer_permission_snapshot,
    _empty_inventory as _cleanup_support__empty_inventory,
)
from tests.infrastructure.mdb.components.takeoff_hydration_support import (
    _Connection as _takeoff_hydration_support__Connection,
    _Cursor as _takeoff_hydration_support__Cursor,
    _Schema as _takeoff_hydration_support__Schema,
    _hydrate as _takeoff_hydration_support__hydrate,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class ReaderSqlCleanupTests(unittest.TestCase):
    def test_sql_shared_annotation_reader_does_not_acknowledge_partial_data(self):
        class _FailingCursor:
            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc_value, _traceback):
                return False

            @staticmethod
            def execute(_sql, *_params):
                raise pyodbc.Error("08S01", "snapshot hydration failed")

        class _Connection:
            @staticmethod
            def cursor():
                return _FailingCursor()

        reader = SqlProjectReader.__new__(SqlProjectReader)
        reader.logger = logging.getLogger("tests.sql_strict_shared_reader")
        with self.assertRaisesRegex(pyodbc.Error, "snapshot hydration failed"):
            reader._parse_bid_annotations_for_bid(
                _Connection(),
                "1",
                [],
                CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema),
            )

    def test_sql_parse_file_uses_one_snapshot_transaction(self):
        class _Cursor:
            def __init__(self):
                self.executed = []

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc_value, _traceback):
                return False

            def execute(self, sql, *_params):
                self.executed.append(sql)
                return self

        class _Lease:
            def __init__(self):
                self.cursor_value = _Cursor()
                self.commits = 0
                self.rollbacks = 0

            def cursor(self):
                return self.cursor_value

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        class _Connections:
            def __init__(self):
                self.lease = _Lease()
                self.autocommit = None

            @contextlib.contextmanager
            def connection(self, _request, *, autocommit=False):
                self.autocommit = autocommit
                yield self.lease

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        connections = _Connections()
        reader = SqlProjectReader(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=connections,
        )
        with patch.object(
            reader,
            "parse_file_connection",
            return_value=("hierarchy", {}),
        ) as parse:
            result = reader.parse_file(descriptor.database_id)
        self.assertEqual(result, ("hierarchy", {}))
        self.assertFalse(connections.autocommit)
        self.assertEqual(
            connections.lease.cursor_value.executed,
            ["SET TRANSACTION ISOLATION LEVEL SNAPSHOT", "BEGIN TRANSACTION"],
        )
        self.assertEqual(connections.lease.commits, 2)
        self.assertEqual(connections.lease.rollbacks, 0)
        parse.assert_called_once_with(descriptor.database_id, connections.lease)

    def test_sql_parse_file_rolls_back_failed_snapshot(self):
        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc_value, _traceback):
                return False

            def execute(self, _sql, *_params):
                return self

        class _Lease:
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

        class _Connections:
            def __init__(self):
                self.lease = _Lease()

            @contextlib.contextmanager
            def connection(self, _request, *, autocommit=False):
                self.autocommit = autocommit
                yield self.lease

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        connections = _Connections()
        reader = SqlProjectReader(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=connections,
        )
        with (
            patch.object(
                reader,
                "parse_file_connection",
                side_effect=RuntimeError("hierarchy failed"),
            ),
            self.assertRaisesRegex(RuntimeError, "hierarchy failed"),
        ):
            reader.parse_file(descriptor.database_id)
        self.assertFalse(connections.autocommit)
        self.assertEqual(connections.lease.commits, 1)
        self.assertEqual(connections.lease.rollbacks, 1)

    def test_sql_shared_reader_connection_is_snapshot_scoped(self):
        class _Cursor:
            def __init__(self):
                self.executed = []

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc_value, _traceback):
                return False

            def execute(self, sql, *_params):
                self.executed.append(sql)
                return self

        class _Lease:
            def __init__(self):
                self.cursor_value = _Cursor()
                self.commits = 0
                self.rollbacks = 0

            def cursor(self):
                return self.cursor_value

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        class _Connections:
            def __init__(self):
                self.lease = _Lease()
                self.autocommit = None

            @contextlib.contextmanager
            def connection(self, _request, *, autocommit=False):
                self.autocommit = autocommit
                yield self.lease

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        connections = _Connections()
        reader = SqlProjectReader(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=connections,
        )
        with reader._connection(descriptor.database_id) as lease:
            self.assertIs(lease, connections.lease)
        self.assertFalse(connections.autocommit)
        self.assertEqual(
            connections.lease.cursor_value.executed,
            ["SET TRANSACTION ISOLATION LEVEL SNAPSHOT", "BEGIN TRANSACTION"],
        )
        self.assertEqual(connections.lease.commits, 2)
        self.assertEqual(connections.lease.rollbacks, 0)

    def test_sql_reader_rejects_invalid_schema_before_domain_queries(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        reader = SqlProjectReader(
            registry,
            _cleanup_support__CredentialStore(),
            _cleanup_support__InspectionManager(),
        )
        reader._inspector.inspect_request = (
            lambda _request: _cleanup_support__empty_inventory()
        )
        with patch.object(
            MdbReader,
            "parse_file",
            side_effect=AssertionError("domain query ran before schema validation"),
        ):
            with self.assertRaisesRegex(Exception, "Schema mismatch"):
                reader.parse_file(descriptor.database_id)

    def test_sql_reader_returns_canonical_descriptor_hierarchy_identity(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            display_name="SQL Test Database",
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        reader = SqlProjectReader(
            registry,
            _cleanup_support__CredentialStore(),
            _cleanup_support__InspectionManager(),
        )
        reader._validator.validate = lambda _inventory: SimpleNamespace(is_valid=True)
        with (
            patch.object(
                reader,
                "_parse_hierarchy",
                return_value=HierarchyFileEntry(file_path=""),
            ),
            patch.object(reader, "_parse_cdn_types", return_value={}),
        ):
            hierarchy, _cdn_types = reader.parse_file(descriptor.database_id)
        self.assertEqual(hierarchy.file_path, descriptor.database_id)
        self.assertEqual(hierarchy.database_name, descriptor.display_name)
        self.assertEqual(hierarchy.display_name, descriptor.display_name)


class TakeoffHydrationContractTests(unittest.TestCase):
    def test_sql_reader_uses_the_same_complete_takeoff_contract(self):
        takeoff = _takeoff_hydration_support__hydrate(
            SqlProjectReader.__new__(SqlProjectReader)
        )
        self.assertTrue(takeoff.has_valid_contract())
        self.assertEqual(takeoff.condition_uid, "10")
        self.assertFalse(hasattr(takeoff, "layer_uid"))
