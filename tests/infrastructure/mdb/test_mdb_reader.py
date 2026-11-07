from tests.helpers.mdb.operations import (
    _SqliteConnectionWrapper,
    _SqliteCursorWrapper,
    _SqliteMdbOps,
    _SqliteRow,
    _SqliteSchema,
)
from ost_visualizer.infrastructure.database.master_data_identity import (
    DuplicateMasterDataUidError,
)
from ost_visualizer.infrastructure.mdb.connection_manager import MdbConnectionManager
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.schema_compatibility import (
    MdbSchemaInspector,
    UnsupportedMdbSchemaError,
)
from ost_visualizer.infrastructure.mdb.components.takeoff_operations import (
    TakeoffOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.settings_operations import (
    SettingsOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.project_operations import (
    ProjectOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.layer_operations import (
    LayerOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.condition_operations import (
    ConditionOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.condition_folder_operations import (
    ConditionFolderOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.bulk_write_helpers import (
    AccessBulkWriteMixin,
)
from ost_visualizer.infrastructure.mdb.components.bid_operations import (
    BidOperationsMixin,
)
import unittest
import sqlite3
import logging
import os
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
import pyodbc

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.infrastructure.sql.write_schema import CurrentSqlWriteSchema


class MdbReaderPersistenceTests(unittest.TestCase):
    def test_condition_type_reader_rejects_duplicate_physical_uid(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.execute("CREATE TABLE CdnTypes (UID INTEGER, Name TEXT)")
        conn.executemany(
            "INSERT INTO CdnTypes VALUES (7, ?)",
            (("First",), ("Conflicting",)),
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "CdnTypes contains duplicate UID 7",
        ):
            MdbReader._parse_cdn_types(
                _SqliteMdbOps(conn), _SqliteConnectionWrapper(conn)
            )

    def test_condition_type_reader_returns_unique_types_and_tolerates_missing_table(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        ops = _SqliteMdbOps(conn)
        wrapper = _SqliteConnectionWrapper(conn)
        self.assertEqual(MdbReader._parse_cdn_types(ops, wrapper), {})
        conn.execute("CREATE TABLE CdnTypes (UID INTEGER, Name TEXT)")
        conn.executemany(
            "INSERT INTO CdnTypes VALUES (?, ?)",
            ((7, "Walls"), (8, "Floors")),
        )
        cdn_types = MdbReader._parse_cdn_types(ops, wrapper)
        self.assertEqual(list(cdn_types), ["7", "8"])
        self.assertEqual(
            [(cdn.uid, cdn.name) for cdn in cdn_types.values()],
            [("7", "Walls"), ("8", "Floors")],
        )


class MdbReaderSqlCleanupTests(unittest.TestCase):
    def test_access_shared_annotation_reader_retains_optional_table_tolerance(self):
        attempted_tables = []

        class _FailingCursor:
            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc_value, _traceback):
                return False

            @staticmethod
            def execute(sql, *_params):
                attempted_tables.append(sql.split("FROM", 1)[1].split()[0])
                raise pyodbc.Error("42S02", "optional Access table is missing")

        class _Connection:
            @staticmethod
            def cursor():
                return _FailingCursor()

        reader = MdbReader.__new__(MdbReader)
        reader.logger = logging.getLogger("tests.access_tolerant_shared_reader")
        annotations = reader._parse_bid_annotations_for_bid(
            _Connection(),
            "1",
            [],
            CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema),
        )
        self.assertEqual(annotations, [])
        self.assertEqual(
            attempted_tables,
            [
                "BidAnnotationClouds",
                "BidAnnotationOvals",
                "BidAnnotationPolygons",
                "BidAnnotationRects",
                "BidAnnoInk",
                "BidALines",
                "BidDimensions",
                "BidArrows",
                "BidTexts",
                "BidHighlights",
                "BidNamedViews",
                "BidHotLinks",
                "BidCallOuts",
            ],
        )


class _AccessCursor:
    """Cursor of a pyodbc-style Access connection: catalog calls and one SELECT."""

    def __init__(self, connection):
        self._connection = connection
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        return False

    def tables(self, tableType=None):
        self._rows = [
            SimpleNamespace(table_name=name) for name in self._connection.catalog
        ]
        return self

    def columns(self, table=None):
        self._rows = [
            SimpleNamespace(column_name=name)
            for name in self._connection.catalog.get(table, ())
        ]
        return self

    def execute(self, sql):
        self._connection.executed.append(sql)
        self._rows = list(self._connection.cdn_rows)
        return self

    def fetchall(self):
        return self._rows


class _AccessConnection:
    def __init__(self, catalog=None, cdn_rows=()):
        self.catalog = catalog if catalog is not None else {}
        self.cdn_rows = cdn_rows
        self.executed = []

    def cursor(self):
        return _AccessCursor(self)


class _RecordingManager:
    def __init__(self, connection=None):
        self.connection_to_yield = connection
        self.events = []

    @contextmanager
    def connection(self, db_path, autocommit=True):
        self.events.append(("enter", db_path, autocommit))
        try:
            yield self.connection_to_yield
        finally:
            self.events.append(("exit", db_path))

    def close_database(self, db_path):
        self.events.append(("close_database", db_path))

    def close(self):
        self.events.append(("close",))


class MdbReaderConstructionAndLifecycleTests(unittest.TestCase):
    def test_default_logger_and_manager_are_created_per_reader(self):
        first = MdbReader()
        second = MdbReader()
        self.assertEqual(
            first.logger.name, "ost_visualizer.infrastructure.mdb.mdb_reader"
        )
        self.assertIsInstance(first._conn_manager, MdbConnectionManager)
        self.assertIsInstance(second._conn_manager, MdbConnectionManager)
        self.assertIsNot(first._conn_manager, second._conn_manager)

    def test_explicit_logger_and_manager_are_kept(self):
        manager = _RecordingManager()
        logger = logging.getLogger("tests.mdb_reader.explicit")
        reader = MdbReader(conn_manager=manager, logger=logger)
        self.assertIs(reader.logger, logger)
        self.assertIs(reader._conn_manager, manager)

    def test_read_leases_use_autocommit_and_release_on_exit(self):
        connection = _AccessConnection()
        manager = _RecordingManager(connection)
        reader = MdbReader(conn_manager=manager)
        with reader._connection("project.mdb") as leased:
            self.assertIs(leased, connection)
            self.assertEqual(manager.events, [("enter", "project.mdb", True)])
        self.assertEqual(
            manager.events, [("enter", "project.mdb", True), ("exit", "project.mdb")]
        )
        self.assertIs(manager.events[0][2], True)

    def test_close_connection_with_a_path_closes_only_that_database(self):
        manager = _RecordingManager()
        MdbReader(conn_manager=manager).close_connection("project.mdb")
        self.assertEqual(manager.events, [("close_database", "project.mdb")])

    def test_close_connection_without_a_path_closes_the_whole_manager(self):
        for empty in (None, ""):
            with self.subTest(db_path=empty):
                manager = _RecordingManager()
                reader = MdbReader(conn_manager=manager)
                if empty is None:
                    reader.close_connection()
                else:
                    reader.close_connection(empty)
                self.assertEqual(manager.events, [("close",)])

    def test_refresh_connection_closes_only_the_named_database(self):
        manager = _RecordingManager()
        MdbReader(conn_manager=manager).refresh_connection("replaced.mdb")
        self.assertEqual(manager.events, [("close_database", "replaced.mdb")])

    def test_close_errors_from_the_manager_reach_the_caller(self):
        manager = _RecordingManager()
        failure = pyodbc.OperationalError("HY000", "close failed")

        def failing_close(_path):
            raise failure

        manager.close_database = failing_close
        reader = MdbReader(conn_manager=manager)
        for call in (
            lambda: reader.refresh_connection("a.mdb"),
            lambda: reader.close_connection("a.mdb"),
        ):
            with self.assertRaises(pyodbc.OperationalError) as raised:
                call()
            self.assertIs(raised.exception, failure)

    def test_reader_defaults_that_subclasses_override(self):
        reader = MdbReader(conn_manager=_RecordingManager())
        self.assertIs(reader._hydrates_bid_navigation_snapshots(), False)
        self.assertIs(MdbReader._record_caught_read_error(ValueError("x")), False)
        self.assertIs(
            MdbReader._record_caught_read_error(ValueError("x"), "loc"), False
        )

    def test_schema_inspector_wraps_the_leased_connection_and_reader_logger(self):
        connection = _AccessConnection()
        logger = logging.getLogger("tests.mdb_reader.schema")
        reader = MdbReader(conn_manager=_RecordingManager(), logger=logger)
        schema = reader._schema(connection)
        self.assertIsInstance(schema, MdbSchemaInspector)
        self.assertIs(schema.connection, connection)
        self.assertIs(schema.logger, logger)


class MdbReaderCdnTypeAndParseFileTests(unittest.TestCase):
    CDN_SQL = "SELECT [UID], [Name] FROM [CdnTypes]"

    def _reader(self, connection):
        manager = _RecordingManager(connection)
        reader = MdbReader(
            conn_manager=manager, logger=logging.getLogger("tests.mdb_reader.cdn")
        )
        return reader, manager

    @staticmethod
    def _cdn_connection(rows, columns=("UID", "Name")):
        return _AccessConnection(
            catalog={"CdnTypes": list(columns)},
            cdn_rows=[SimpleNamespace(UID=uid, Name=name) for uid, name in rows],
        )

    def test_cdn_types_are_keyed_by_text_uid_and_decode_names(self):
        connection = self._cdn_connection([(7, "Walls"), (8, b"Fl\xf6ors"), (9, None)])
        reader, _manager = self._reader(connection)
        cdn_types = reader._parse_cdn_types(connection)
        self.assertEqual(list(cdn_types), ["7", "8", "9"])
        self.assertEqual(
            [(cdn.uid, cdn.name) for cdn in cdn_types.values()],
            [("7", "Walls"), ("8", "Fl\xf6ors"), ("9", "")],
        )
        self.assertEqual(connection.executed, [self.CDN_SQL])

    def test_missing_optional_table_yields_no_types_and_runs_no_select(self):
        connection = _AccessConnection(catalog={"Bids": ["UID"]})
        reader, _manager = self._reader(connection)
        self.assertEqual(reader._parse_cdn_types(connection), {})
        self.assertEqual(connection.executed, [])

    def test_missing_required_cdn_columns_are_rejected_before_the_select(self):
        for present, missing in ((("UID",), "Name"), (("Name",), "UID")):
            with self.subTest(missing=missing):
                connection = self._cdn_connection([(1, "x")], columns=present)
                reader, _manager = self._reader(connection)
                with self.assertRaisesRegex(
                    UnsupportedMdbSchemaError,
                    f"missing required column CdnTypes.{missing}",
                ):
                    reader._parse_cdn_types(connection)
                self.assertEqual(connection.executed, [])

    def test_duplicate_uids_are_rejected_with_the_table_named(self):
        connection = self._cdn_connection([(7, "First"), (7, "Second")])
        reader, _manager = self._reader(connection)
        with self.assertRaisesRegex(
            DuplicateMasterDataUidError, "CdnTypes contains duplicate UID 7"
        ):
            reader._parse_cdn_types(connection)

    def test_get_cdn_types_reads_inside_one_autocommit_lease(self):
        connection = self._cdn_connection([(3, "Doors")])
        reader, manager = self._reader(connection)
        cdn_types = reader.get_cdn_types("project.mdb")
        self.assertEqual(
            [(cdn.uid, cdn.name) for cdn in cdn_types.values()], [("3", "Doors")]
        )
        self.assertEqual(
            manager.events, [("enter", "project.mdb", True), ("exit", "project.mdb")]
        )

    def test_get_cdn_types_releases_the_lease_when_the_read_fails(self):
        connection = self._cdn_connection([(3, "A"), (3, "B")])
        reader, manager = self._reader(connection)
        with self.assertRaises(DuplicateMasterDataUidError):
            reader.get_cdn_types("project.mdb")
        self.assertEqual(
            manager.events, [("enter", "project.mdb", True), ("exit", "project.mdb")]
        )

    def test_parse_file_returns_hierarchy_and_types_read_in_one_lease(self):
        connection = self._cdn_connection([(5, "Slabs")])
        reader, manager = self._reader(connection)
        hierarchy = object()
        seen = []

        def fake_hierarchy(_self, leased, file_path):
            seen.append((leased, file_path, list(manager.events)))
            return hierarchy

        with patch.object(MdbReader, "_parse_hierarchy", fake_hierarchy):
            result = reader.parse_file("project.mdb")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIs(result[0], hierarchy)
        self.assertEqual(
            [(cdn.uid, cdn.name) for cdn in result[1].values()], [("5", "Slabs")]
        )
        self.assertEqual(
            seen, [(connection, "project.mdb", [("enter", "project.mdb", True)])]
        )
        self.assertEqual(
            manager.events, [("enter", "project.mdb", True), ("exit", "project.mdb")]
        )

    def test_parse_file_failure_releases_the_lease_and_skips_cdn_types(self):
        connection = self._cdn_connection([(5, "Slabs")])
        reader, manager = self._reader(connection)
        failure = UnsupportedMdbSchemaError("broken hierarchy")

        def failing_hierarchy(_self, _leased, _path):
            raise failure

        with patch.object(MdbReader, "_parse_hierarchy", failing_hierarchy):
            with self.assertRaises(UnsupportedMdbSchemaError) as raised:
                reader.parse_file("project.mdb")
        self.assertIs(raised.exception, failure)
        self.assertEqual(connection.executed, [])
        self.assertEqual(
            manager.events, [("enter", "project.mdb", True), ("exit", "project.mdb")]
        )
