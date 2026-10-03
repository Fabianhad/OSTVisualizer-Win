from tests.helpers.sql.strict_sql_fakes import StrictLeaseProxy, strict_manager
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
from ost_visualizer.infrastructure.mdb.components.bid_data_reader import (
    BidDataReaderMixin,
)
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlInfrastructureError,
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
        class _ScriptedCursor:
            def __init__(self, fail_on):
                self.fail_on = fail_on
                self.executes = 0

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc_value, _traceback):
                return False

            def execute(self, _sql, *_params):
                self.executes += 1
                if self.executes == self.fail_on:
                    raise pyodbc.Error("08S01", "snapshot hydration failed")
                return self

            @staticmethod
            def fetchall():
                return []

        class _Connection:
            def __init__(self, cursor):
                self._cursor = cursor

            def cursor(self):
                return self._cursor

        reader = SqlProjectReader.__new__(SqlProjectReader)
        reader.logger = logging.getLogger("tests.sql_strict_shared_reader")
        schema = CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema)
        complete = _ScriptedCursor(fail_on=0)
        self.assertEqual(
            reader._parse_bid_annotations_for_bid(
                _Connection(complete), "1", [], schema
            ),
            [],
        )
        self.assertGreater(complete.executes, 1)
        # A failure in ANY annotation table, not just the first, must abort the
        # whole read instead of returning the annotations read so far.
        for failing_query in range(1, complete.executes + 1):
            with self.subTest(failing_query=failing_query):
                cursor = _ScriptedCursor(fail_on=failing_query)
                with self.assertRaisesRegex(pyodbc.Error, "snapshot hydration failed"):
                    reader._parse_bid_annotations_for_bid(
                        _Connection(cursor), "1", [], schema
                    )
                self.assertEqual(cursor.executes, failing_query)

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
            def connection(self, request, *, autocommit=False):
                self.request = request
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
            connection_manager=strict_manager(connections),
        )
        with patch.object(
            reader,
            "parse_file_connection",
            return_value=("hierarchy", {}),
        ) as parse:
            result = reader.parse_file(descriptor.database_id)
        self.assertEqual(result, ("hierarchy", {}))
        self.assertTrue(connections.request.read_only)
        self.assertEqual(connections.request.location, descriptor.sql_location)
        self.assertFalse(connections.autocommit)
        self.assertEqual(
            connections.lease.cursor_value.executed,
            ["SET TRANSACTION ISOLATION LEVEL SNAPSHOT", "BEGIN TRANSACTION"],
        )
        self.assertEqual(connections.lease.commits, 2)
        self.assertEqual(connections.lease.rollbacks, 0)
        parse.assert_called_once()
        self.assertEqual(parse.call_args.args[0], descriptor.database_id)
        self.assertIs(parse.call_args.args[1]._inner, connections.lease)

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
            connection_manager=strict_manager(connections),
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
            connection_manager=strict_manager(connections),
        )
        with reader._connection(descriptor.database_id) as lease:
            self.assertIs(lease._inner, connections.lease)
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
        manager = _cleanup_support__InspectionManager()
        reader = SqlProjectReader(
            registry,
            _cleanup_support__CredentialStore(),
            strict_manager(manager),
        )
        with (
            patch.object(
                reader,
                "_parse_hierarchy",
                side_effect=AssertionError("hierarchy query ran before validation"),
            ),
            patch.object(
                reader,
                "_parse_cdn_types",
                side_effect=AssertionError("domain query ran before validation"),
            ),
            self.assertRaises(SqlInfrastructureError) as raised,
        ):
            reader.parse_file(descriptor.database_id)
        self.assertEqual(raised.exception.details.code, SqlErrorCode.SCHEMA_MISMATCH)
        self.assertEqual(
            str(raised.exception),
            "Schema mismatch: ostv.DatabaseMetadata.SchemaVersion",
        )
        self.assertTrue(raised.exception.read_only_required)
        # The failed validation still ends the snapshot transaction cleanly.
        self.assertEqual(manager.lease.rollbacks, 1)

    def test_sql_reader_rejects_unregistered_descriptor_before_connecting(self):
        class _NeverConnects:
            def connection(self, _request, *, autocommit=False):
                raise AssertionError("must not connect for an unknown database")

        reader = SqlProjectReader(
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            strict_manager(_NeverConnects()),
        )
        with self.assertRaises(SqlInfrastructureError) as raised:
            reader.parse_file("not-registered")
        self.assertEqual(raised.exception.details.code, SqlErrorCode.DATABASE_MISSING)

    def test_failed_rollback_does_not_mask_the_original_read_error(self):
        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc_value, _traceback):
                return False

            def execute(self, _sql, *_params):
                return self

        class _Lease:
            @staticmethod
            def cursor():
                return _Cursor()

            @staticmethod
            def commit():
                pass

            @staticmethod
            def rollback():
                raise pyodbc.Error("08S01", "rollback failed")

        class _Connections:
            @contextlib.contextmanager
            def connection(self, _request, *, autocommit=False):
                yield _Lease()

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        reader = SqlProjectReader(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=strict_manager(_Connections()),
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
            strict_manager(_cleanup_support__InspectionManager()),
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
        self.assertEqual(descriptor.display_name, "SQL Test Database")
        self.assertNotEqual(hierarchy.file_path, "")


class TakeoffHydrationContractTests(unittest.TestCase):
    def test_sql_reader_uses_the_same_complete_takeoff_contract(self):
        takeoff = _takeoff_hydration_support__hydrate(
            SqlProjectReader.__new__(SqlProjectReader)
        )
        self.assertTrue(takeoff.has_valid_contract())
        self.assertEqual(
            takeoff, _takeoff_hydration_support__hydrate(BidDataReaderMixin())
        )
        self.assertEqual(takeoff.uid, "4485")
        self.assertEqual(takeoff.position, [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(
            (takeoff.page_uid, takeoff.area_uid, takeoff.parent_uid, takeoff.curve),
            ("20", "0", "0", 0),
        )
        self.assertEqual(takeoff.condition_uid, "10")
        self.assertFalse(hasattr(takeoff, "layer_uid"))


from tests.helpers.sql.strict_sql_fakes import (  # noqa: E402
    Reply,
    StrictSqlServer,
    snapshot_transaction_rules,
    sql_server_error,
)


class ReaderStrictSnapshotTests(unittest.TestCase):
    """SqlProjectReader's snapshot transaction against the strict pyodbc model."""

    def _reader(self, server):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        reader = SqlProjectReader(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=server.manager(),
        )
        return reader, descriptor

    def _server(self):
        server = StrictSqlServer()
        snapshot_transaction_rules(server)
        server.on("SELECT 1", Reply.rows((1,)))
        return server

    def test_read_runs_in_a_snapshot_transaction_that_is_committed_after_the_work(self):
        server = self._server()
        reader, descriptor = self._reader(server)

        def work(lease):
            with lease.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone()

        with server.patched():
            with reader._connection(descriptor.database_id) as lease:
                self.assertEqual(work(lease), (1,))
        raw = server.connections[0]
        self.assertFalse(server.connect_calls[0]["autocommit"])
        self.assertIn(
            "ApplicationIntent=ReadOnly", server.connect_calls[0]["connection_string"]
        )
        self.assertEqual(
            server.event_kinds(1),
            [
                "cursor_open",
                "execute",
                "commit",
                "execute",
                "cursor_close",
                "cursor_open",
                "execute",
                "cursor_close",
                "commit",
                "close",
            ],
        )
        self.assertEqual(
            server.statements(1)[:2],
            ["SET TRANSACTION ISOLATION LEVEL SNAPSHOT", "BEGIN TRANSACTION"],
        )
        self.assertEqual((raw.commits, raw.rollbacks), (2, 0))
        server.assert_everything_closed()

    def test_every_failure_path_rolls_back_and_closes_the_physical_connection(self):
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
                reader, descriptor = self._reader(server)
                with server.patched():
                    with self.assertRaisesRegex(RuntimeError, "body failed"):
                        with reader._connection(descriptor.database_id):
                            raise RuntimeError("body failed")
                raw = server.connections[0]
                self.assertEqual((raw.commits, raw.rollbacks), (1, 1))
                server.assert_everything_closed()

    def test_failed_final_commit_rolls_back_and_surfaces_the_driver_failure(self):
        server = self._server()
        # the first commit is the snapshot preamble; the second is the final one
        server.fail(
            "commit",
            sql_server_error("08S01", "Communication link failure"),
            skip=1,
        )
        reader, descriptor = self._reader(server)
        with server.patched():
            with self.assertRaises(SqlInfrastructureError) as raised:
                with reader._connection(descriptor.database_id):
                    pass
        self.assertEqual(raised.exception.details.code, SqlErrorCode.CONNECTION_FAILED)
        raw = server.connections[0]
        self.assertEqual((raw.commits, raw.rollbacks), (2, 1))
        server.assert_everything_closed()

    def test_database_without_snapshot_isolation_fails_the_first_read_not_silently(
        self,
    ):
        server = StrictSqlServer(snapshot_enabled=False)
        snapshot_transaction_rules(server)
        server.on("SELECT 1", Reply.rows((1,)))
        reader, descriptor = self._reader(server)
        with server.patched():
            with self.assertRaises(SqlInfrastructureError):
                with reader._connection(descriptor.database_id) as lease:
                    with lease.cursor() as cursor:
                        cursor.execute("SELECT 1")
        raw = server.connections[0]
        self.assertEqual(raw.rollbacks, 1)
        server.assert_everything_closed()


class ReaderConstructionAndContractTests(unittest.TestCase):
    """Survivors of the second-pass mutation sweep over reader.py."""

    def _reader(self, **kwargs):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        return (
            SqlProjectReader(registry, _cleanup_support__CredentialStore(), **kwargs),
            descriptor,
        )

    def test_logger_and_connection_manager_default_or_use_the_injected_collaborators(
        self,
    ):
        from ost_visualizer.infrastructure.sql.connection_manager import (
            SqlConnectionManager,
        )

        reader, _descriptor = self._reader()
        self.assertEqual(reader.logger.name, "ost_visualizer.infrastructure.sql.reader")
        self.assertIsInstance(reader._sql_connections, SqlConnectionManager)
        logger = logging.getLogger("tests.injected_reader_logger")
        manager = SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])
        reader, _descriptor = self._reader(logger=logger, connection_manager=manager)
        self.assertIs(reader.logger, logger)
        self.assertIs(reader._sql_connections, manager)

    def test_write_schema_contract_is_the_canonical_v1_core_schema(self):
        reader, _descriptor = self._reader()
        schema = reader._schema(object())
        self.assertIsInstance(schema, CurrentSqlWriteSchema)
        self.assertTrue(schema.table_exists("Bids"))
        self.assertFalse(
            schema.table_exists("Sessions")
        )  # ostv tables are not core tables
        self.assertIs(reader._schema(object()), schema)

    def test_sql_navigation_loads_hydrate_snapshots_and_read_errors_are_recorded(self):
        reader, _descriptor = self._reader()
        self.assertIs(reader._hydrates_bid_navigation_snapshots(), True)
        self.assertIs(reader._record_caught_read_error(RuntimeError("x")), True)
        # the Access reader is the opposite on both points
        self.assertIs(
            MdbReader._hydrates_bid_navigation_snapshots(MdbReader.__new__(MdbReader)),
            False,
        )

    def test_hierarchy_and_cdn_types_are_read_from_the_same_validated_connection(self):
        reader, descriptor = self._reader()
        connection = object()
        calls = []
        hierarchy = HierarchyFileEntry(file_path="")
        reader._validator.validate = lambda _inventory: SimpleNamespace(is_valid=True)
        reader._inspector.inspect_connection = lambda received: (
            calls.append(("inspect", received)) or None
        )
        with (
            patch.object(
                reader,
                "_parse_hierarchy",
                side_effect=lambda *args: calls.append(("hierarchy", args))
                or hierarchy,
            ),
            patch.object(
                reader,
                "_parse_cdn_types",
                side_effect=lambda *args: calls.append(("cdn", args)) or {"1": "x"},
            ),
        ):
            result_hierarchy, cdn_types = reader.parse_file_connection(
                descriptor.database_id, connection
            )
        self.assertIs(result_hierarchy, hierarchy)
        self.assertEqual(cdn_types, {"1": "x"})
        self.assertEqual(
            calls,
            [
                ("inspect", connection),
                ("hierarchy", (connection, descriptor.database_id)),
                ("cdn", (connection,)),
            ],
        )

    def test_unregistered_descriptor_after_validation_is_a_lookup_error_not_a_partial_result(
        self,
    ):
        reader, descriptor = self._reader()
        reader._validator.validate = lambda _inventory: SimpleNamespace(is_valid=True)
        reader._inspector.inspect_connection = lambda _connection: None
        with (
            patch.object(
                reader,
                "_parse_hierarchy",
                return_value=HierarchyFileEntry(file_path=""),
            ),
            patch.object(reader, "_parse_cdn_types", return_value={}),
            self.assertRaisesRegex(LookupError, "not registered"),
        ):
            reader.parse_file_connection("unregistered-id", object())
