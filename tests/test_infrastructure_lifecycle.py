import logging
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import patch
import pyodbc
from ost_visualizer.infrastructure import providers
from ost_visualizer.infrastructure.mdb import database_creator
from ost_visualizer.infrastructure.mdb.components.annotation_operations import (
    AnnotationOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.bid_operations import (
    BidOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.bulk_write_helpers import (
    AccessBulkWriteMixin,
)
from ost_visualizer.infrastructure.mdb.components.condition_folder_operations import (
    ConditionFolderOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.condition_operations import (
    ConditionOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.constants import (
    TAKEOFF_REFERENCE_TABLES,
)
from ost_visualizer.infrastructure.mdb.components.layer_operations import (
    LayerOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.settings_operations import (
    SettingsOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.takeoff_operations import (
    TakeoffOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.schema_contract import DEFAULT_LAYER_ROWS
from ost_visualizer.infrastructure.services.license_validation_scheduler import (
    LicenseValidationScheduler,
)


class _SqliteCursorWrapper:
    def __init__(self, connection):
        self._connection = connection
        self._cursor = None

    def execute(self, query, *params):
        self._cursor = self._connection.execute(query, params)

    def fetchone(self):
        if self._cursor is None:
            return None
        row = self._cursor.fetchone()
        if row is None or self._cursor.description is None:
            return row
        columns = [description[0] for description in self._cursor.description]
        return _SqliteRow(columns, row)

    @property
    def rowcount(self):
        return self._cursor.rowcount if self._cursor is not None else -1


class _SqliteRow:
    def __init__(self, columns, values):
        self._columns = list(columns)
        self._values = tuple(values)
        self._by_name = dict(zip(self._columns, self._values))

    def __getitem__(self, index):
        return self._values[index]

    def __getattr__(self, name):
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class _SqliteConnectionWrapper:
    def __init__(self, connection):
        self._connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc, _tb):
        if exc_type is None:
            self._connection.commit()
        return False

    def cursor(self):
        return _SqliteCursorWrapper(self._connection)


class _SqliteSchema:
    def __init__(self, connection):
        self._connection = connection

    def optional_table_missing(self, table_name):
        row = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is None

    def column_exists(self, table_name, column_name):
        return any(
            row[1] == column_name
            for row in self._connection.execute(f"PRAGMA table_info({table_name})")
        )


class _SqliteMdbOps(
    AccessBulkWriteMixin,
    BidOperationsMixin,
    ConditionFolderOperationsMixin,
    LayerOperationsMixin,
    SettingsOperationsMixin,
    TakeoffOperationsMixin,
):
    logger = logging.getLogger("test")

    def __init__(self, connection):
        self._connection_ref = connection
        self._schema_ref = _SqliteSchema(connection)

    def _connection(self, _db_path):
        return _SqliteConnectionWrapper(self._connection_ref)

    def _schema(self, _connection):
        return self._schema_ref

    def _require_write_columns(self, _schema, _table, _columns):
        pass

    @staticmethod
    def _record_caught_mutation_error(_exc):
        return False


class _RecordingSchema:
    def __init__(self, columns_by_table=None):
        self.columns_by_table = columns_by_table or {
            "BidTakeoffs": {
                "UID",
                "BidAreaUID",
                "BidConditionUID",
                "IsNegativeQuantity",
            }
        }

    def require_column(self, table, column):
        if not self.column_exists(table, column):
            raise RuntimeError(f"Missing {table}.{column}")

    def optional_table_missing(self, table):
        return table not in self.columns_by_table

    def column_exists(self, table, column):
        return column in self.columns_by_table.get(table, set())


class _RecordingCursor:
    def __init__(self, ops):
        self.ops = ops

    def execute(self, query, *params):
        self.ops.executions.append((query, tuple(params)))
        self.ops.execute_count += 1
        if (
            self.ops.fail_on_execute is not None
            and self.ops.execute_count == self.ops.fail_on_execute
        ):
            raise RuntimeError("forced chunk failure")
        if self.ops.fail_once_hy001 and not self.ops.failed_hy001:
            self.ops.failed_hy001 = True
            raise pyodbc.OperationalError(
                "HY001",
                "[HY001] [Microsoft][ODBC Microsoft Access Driver] "
                "System resource exceeded.",
            )


class _RecordingConnection:
    def __init__(self, ops):
        self.ops = ops

    def cursor(self):
        return _RecordingCursor(self.ops)


class _RecordingTakeoffOps(AccessBulkWriteMixin, TakeoffOperationsMixin):
    def __init__(
        self,
        schema=None,
        fail_on_execute=None,
        fail_once_hy001=False,
    ):
        self.schema = schema or _RecordingSchema()
        self.fail_on_execute = fail_on_execute
        self.fail_once_hy001 = fail_once_hy001
        self.failed_hy001 = False
        self.execute_count = 0
        self.executions = []
        self.connection_count = 0
        self.commits = 0
        self.rollbacks = 0
        self.logger = logging.getLogger("tests.recording_takeoff_ops")

    @contextmanager
    def _connection(self, _db_path):
        self.connection_count += 1
        try:
            yield _RecordingConnection(self)
        except Exception:
            self.rollbacks += 1
            raise
        else:
            self.commits += 1

    def _schema(self, _connection):
        return self.schema

    def _require_write_columns(self, schema, table, columns):
        for column in columns:
            schema.require_column(table, column)

    @staticmethod
    def _record_caught_mutation_error(_exc):
        return False


class InfrastructureLifecycleTests(unittest.TestCase):
    def test_license_validation_scheduler_stop_releases_thread_reference(self):
        scheduler = LicenseValidationScheduler(interval_seconds=60)
        scheduler.set_task(lambda: None)
        scheduler.start()
        scheduler.stop()
        self.assertIsNone(scheduler._thread)

    def test_license_validation_scheduler_clear_task_releases_callback(self):
        retained = object()
        scheduler = LicenseValidationScheduler(
            interval_seconds=60, task=lambda retained=retained: retained
        )
        scheduler.clear_task()
        self.assertIsNone(scheduler._task)

    def test_pdf_page_size_renderer_closes_when_page_read_fails(self):
        class FakeRenderer:
            last_instance = None

            def __init__(self):
                self.closed = False
                FakeRenderer.last_instance = self

            def open(self, _path):
                return True

            def page_count(self):
                return 1

            def page_size(self, _page_index):
                raise RuntimeError("page failed")

            def close(self):
                self.closed = True

        original_renderer = providers._ost_pdf.PDFRenderer
        providers._ost_pdf.PDFRenderer = FakeRenderer
        try:
            service_provider = providers.InfrastructureServiceProvider(
                logger=logging.getLogger("test"),
                callback_bridge_factory=lambda: None,
                database_session_registry=object(),
            )
            with self.assertLogs("test", level="ERROR"):
                self.assertEqual(service_provider.get_pdf_page_sizes("bad.pdf"), [])
            self.assertTrue(FakeRenderer.last_instance.closed)
        finally:
            providers._ost_pdf.PDFRenderer = original_renderer

    def test_infrastructure_provider_reuses_one_owned_default_connection_manager(self):
        class FalseyManager:
            def __bool__(self):
                return False

        explicit_manager = FalseyManager()
        service_provider = providers.InfrastructureServiceProvider(
            logger=logging.getLogger("test"),
            callback_bridge_factory=lambda: None,
            database_session_registry=object(),
            descriptor_registry=object(),
            credential_store=object(),
        )
        with (
            patch.object(providers, "DatabaseProjectReader") as reader_type,
            patch.object(providers, "DatabaseProjectWriter") as writer_type,
        ):
            default_reader = service_provider.get_mdb_reader()
            self.assertIs(service_provider.get_mdb_reader(), default_reader)
            default_writer = service_provider.get_mdb_writer()
            self.assertIs(service_provider.get_mdb_writer(), default_writer)
            default_manager = reader_type.call_args_list[0].args[0]
            self.assertIs(writer_type.call_args_list[0].args[0], default_manager)
            service_provider.get_mdb_reader(explicit_manager)
            service_provider.get_mdb_writer(explicit_manager)
            self.assertIs(reader_type.call_args_list[1].args[0], explicit_manager)
            self.assertIs(writer_type.call_args_list[1].args[0], explicit_manager)
            self.assertEqual(reader_type.call_count, 2)
            self.assertEqual(writer_type.call_count, 2)

    def test_database_creator_closes_cursor_and_connection_on_schema_failure(self):
        class FakeCursor:
            def __init__(self):
                self.closed = False

            def execute(self, _sql):
                raise RuntimeError("ddl failed")

            def close(self):
                self.closed = True

        class FakeConnection:
            def __init__(self):
                self.cursor_instance = FakeCursor()
                self.rolled_back = False
                self.closed = False

            def cursor(self):
                return self.cursor_instance

            def rollback(self):
                self.rolled_back = True

            def close(self):
                self.closed = True

        fake_connection = FakeConnection()
        original_connect = database_creator.pyodbc.connect
        database_creator.pyodbc.connect = (
            lambda *_args, **_call_options: fake_connection
        )
        try:
            creator = database_creator.DatabaseCreator()
            with self.assertRaises(RuntimeError):
                creator._create_schema("test.mdb")
        finally:
            database_creator.pyodbc.connect = original_connect
        self.assertTrue(fake_connection.cursor_instance.closed)
        self.assertTrue(fake_connection.rolled_back)
        self.assertTrue(fake_connection.closed)

    def test_database_creator_preserves_schema_error_across_cleanup_failures(self):
        class FakeCursor:
            def execute(self, _sql):
                raise RuntimeError("ddl failed")

            def close(self):
                raise RuntimeError("cursor close failed")

        class FakeConnection:
            def __init__(self):
                self.closed = False

            def cursor(self):
                return FakeCursor()

            def rollback(self):
                raise RuntimeError("rollback failed")

            def close(self):
                self.closed = True

        fake_connection = FakeConnection()
        original_connect = database_creator.pyodbc.connect
        database_creator.pyodbc.connect = (
            lambda *_args, **_call_options: fake_connection
        )
        try:
            creator = database_creator.DatabaseCreator(
                logging.getLogger("test.database_creator.cleanup")
            )
            with self.assertLogs(creator._logger, level="ERROR"):
                with self.assertRaisesRegex(RuntimeError, "ddl failed"):
                    creator._create_schema("test.mdb")
        finally:
            database_creator.pyodbc.connect = original_connect
        self.assertTrue(fake_connection.closed)

    def test_database_creator_closes_connection_before_raising_cleanup_error(self):
        class FakeCursor:
            def execute(self, _sql):
                return None

            def close(self):
                raise RuntimeError("cursor close failed")

        class FakeConnection:
            def __init__(self):
                self.closed = False

            def cursor(self):
                return FakeCursor()

            def commit(self):
                return None

            def rollback(self):
                raise AssertionError("successful schema should not roll back")

            def close(self):
                self.closed = True

        fake_connection = FakeConnection()
        original_connect = database_creator.pyodbc.connect
        database_creator.pyodbc.connect = (
            lambda *_args, **_call_options: fake_connection
        )
        try:
            creator = database_creator.DatabaseCreator(
                logging.getLogger("test.database_creator.success_cleanup")
            )
            with self.assertLogs(creator._logger, level="ERROR"):
                with self.assertRaisesRegex(RuntimeError, "cursor close failed"):
                    creator._create_schema("test.mdb")
        finally:
            database_creator.pyodbc.connect = original_connect
        self.assertTrue(fake_connection.closed)

    def test_database_creator_preserves_metadata_error_when_dao_close_fails(self):
        class FakeDatabase:
            def TableDefs(self, _table_name):
                raise RuntimeError("metadata failed")

            def Close(self):
                raise RuntimeError("DAO close failed")

        engine = SimpleNamespace(OpenDatabase=lambda _path: FakeDatabase())
        creator = database_creator.DatabaseCreator(
            logging.getLogger("test.database_creator.dao_cleanup")
        )
        with patch("win32com.client.Dispatch", return_value=engine):
            with self.assertLogs(creator._logger, level="ERROR"):
                with self.assertRaisesRegex(RuntimeError, "metadata failed"):
                    creator._apply_reference_schema_metadata("test.mdb")

    def test_database_creator_uses_unique_argument_based_vbs_scripts(self):
        commands = []
        scripts = []

        def run(command, **_call_options):
            commands.append(command)
            script_path = Path(command[2])
            scripts.append((script_path, script_path.read_text(encoding="utf-8")))
            Path(command[3]).touch()
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp_dir:
            first_path = Path(tmp_dir) / "first;database.mdb"
            second_path = Path(tmp_dir) / "second.mdb"
            with patch.object(database_creator.subprocess, "run", side_effect=run):
                creator = database_creator.DatabaseCreator()
                creator._create_blank_mdb(first_path)
                creator._create_blank_mdb(second_path)
        self.assertNotEqual(commands[0][2], commands[1][2])
        self.assertEqual(commands[0][3], str(first_path))
        self.assertEqual(commands[1][3], str(second_path))
        for script_path, script in scripts:
            self.assertFalse(script_path.exists())
            self.assertIn("WScript.Arguments(0)", script)
            self.assertNotIn(str(first_path), script)
            self.assertNotIn(str(second_path), script)

    def test_database_creator_reports_major_progress_stages(self):
        class FakeDatabaseCreator(database_creator.DatabaseCreator):
            def _create_blank_mdb(self, db_path):
                Path(db_path).touch()

            def _create_schema(self, db_path, progress_callback=None):
                self._report_progress(progress_callback, "schema tables")
                self._report_progress(progress_callback, "schema field metadata")
                self._report_progress(progress_callback, "schema indexes")
                self._report_progress(progress_callback, "schema relationships")

            def _insert_seed_data(self, db_path, name, progress_callback=None):
                self._report_progress(progress_callback, "default data")

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "created.mdb"
            reports = []
            creator = FakeDatabaseCreator()
            self.assertTrue(
                creator.create_database(
                    db_path,
                    "Created",
                    progress_callback=reports.append,
                )
            )
        self.assertEqual(
            reports,
            [
                "database file",
                "schema tables",
                "schema field metadata",
                "schema indexes",
                "schema relationships",
                "default data",
                "finalizing",
            ],
        )

    def test_database_creator_seeds_default_layers_from_schema_contract(self):
        class FakeCursor:
            def __init__(self):
                self.calls = []

            def execute(self, sql, *params):
                self.calls.append((sql, params))

            def close(self):
                pass

        class FakeConnection:
            def __init__(self):
                self.cursor_instance = FakeCursor()
                self.committed = False
                self.closed = False

            def cursor(self):
                return self.cursor_instance

            def commit(self):
                self.committed = True

            def rollback(self):
                raise AssertionError("seed data should not roll back")

            def close(self):
                self.closed = True

        fake_connection = FakeConnection()
        original_connect = database_creator.pyodbc.connect
        database_creator.pyodbc.connect = (
            lambda *_args, **_call_options: fake_connection
        )
        try:
            creator = database_creator.DatabaseCreator()
            creator._insert_seed_data("test.mdb", "Created")
        finally:
            database_creator.pyodbc.connect = original_connect
        layer_params = [
            params
            for sql, params in fake_connection.cursor_instance.calls
            if "INSERT INTO [BidLayers]" in sql
        ]
        self.assertEqual(
            layer_params,
            [
                (name, -1 if show else 0, -1 if locked else 0, sequence)
                for name, show, locked, sequence in DEFAULT_LAYER_ROWS
            ],
        )
        self.assertTrue(fake_connection.committed)
        self.assertTrue(fake_connection.closed)

    def test_delete_bid_removes_bid_scoped_children_without_direct_links(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute(
            """
            CREATE TABLE BidPages (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidTakeoffs (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID),
                BidPageUID INTEGER REFERENCES BidPages(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidDimensions (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID),
                BidPageUID INTEGER REFERENCES BidPages(UID),
                BidTakeoffFromUID INTEGER REFERENCES BidTakeoffs(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidAreas (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidTypAreas (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidLaborCostCodes (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidTimeCardStates (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidTimeCards (
                UID INTEGER PRIMARY KEY,
                BidTimeCardStateUID INTEGER REFERENCES BidTimeCardStates(UID),
                BidEmployeeUID INTEGER,
                BidAreaUID INTEGER REFERENCES BidAreas(UID),
                BidTypicalAreaUID INTEGER REFERENCES BidTypAreas(UID),
                BidLaborCostCodeUID INTEGER REFERENCES BidLaborCostCodes(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidPercents (
                UID INTEGER PRIMARY KEY,
                BidTakeoffUID INTEGER REFERENCES BidTakeoffs(UID),
                BidLaborCostCodeUID INTEGER REFERENCES BidLaborCostCodes(UID),
                BidTimeCardStateUID INTEGER REFERENCES BidTimeCardStates(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidTypAreaCounts (
                UID INTEGER PRIMARY KEY,
                BidAreaUID INTEGER REFERENCES BidAreas(UID),
                BidTypAreaUID INTEGER REFERENCES BidTypAreas(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidPageSettings (
                UID INTEGER PRIMARY KEY,
                BidPageUID INTEGER REFERENCES BidPages(UID),
                BidAreaUID INTEGER REFERENCES BidAreas(UID),
                BidTypAreaUID INTEGER REFERENCES BidTypAreas(UID)
            )
            """
        )
        conn.execute("INSERT INTO Bids (UID) VALUES (1)")
        conn.execute("INSERT INTO BidAreas (UID, BidUID) VALUES (30, 1)")
        conn.execute("INSERT INTO BidTypAreas (UID, BidUID) VALUES (40, 1)")
        conn.execute("INSERT INTO BidLaborCostCodes (UID, BidUID) VALUES (50, 1)")
        conn.execute("INSERT INTO BidTimeCardStates (UID, BidUID) VALUES (60, 1)")
        conn.execute(
            "INSERT INTO BidTakeoffs (UID, BidUID, BidPageUID) VALUES (10, 1, NULL)"
        )
        conn.execute(
            "INSERT INTO BidDimensions "
            "(UID, BidUID, BidPageUID, BidTakeoffFromUID) VALUES (20, 1, NULL, 10)"
        )
        conn.execute(
            "INSERT INTO BidTimeCards "
            "(UID, BidTimeCardStateUID, BidEmployeeUID, BidAreaUID, "
            "BidTypicalAreaUID, BidLaborCostCodeUID) "
            "VALUES (70, 60, NULL, 30, 40, 50)"
        )
        conn.execute(
            "INSERT INTO BidPercents "
            "(UID, BidTakeoffUID, BidLaborCostCodeUID, BidTimeCardStateUID) "
            "VALUES (80, NULL, 50, 60)"
        )
        conn.execute(
            "INSERT INTO BidTypAreaCounts (UID, BidAreaUID, BidTypAreaUID) "
            "VALUES (90, 30, 40)"
        )
        conn.execute(
            "INSERT INTO BidPageSettings "
            "(UID, BidPageUID, BidAreaUID, BidTypAreaUID) "
            "VALUES (100, NULL, 30, 40)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_bids("bid.mdb", ["1"]))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 0)
        for table in (
            "BidTakeoffs",
            "BidDimensions",
            "BidTimeCards",
            "BidPercents",
            "BidTypAreaCounts",
            "BidPageSettings",
            "BidAreas",
            "BidTypAreas",
            "BidLaborCostCodes",
            "BidTimeCardStates",
        ):
            with self.subTest(table=table):
                self.assertEqual(
                    conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                    0,
                )

    def test_delete_bid_removes_bid_settings_before_bid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute(
            """
            CREATE TABLE BidSettings (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID)
            )
            """
        )
        conn.execute("INSERT INTO Bids (UID) VALUES (1)")
        conn.execute("INSERT INTO BidSettings (UID, BidUID) VALUES (2, 1)")
        self.assertTrue(_SqliteMdbOps(conn).delete_bids("bid.mdb", ["1"]))
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidSettings").fetchone()[0], 0
        )
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 0)

    def test_delete_bid_clears_cross_bid_selected_page_before_page_delete(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute(
            """
            CREATE TABLE BidPages (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidSettings (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID),
                BidPageSelectedUID INTEGER REFERENCES BidPages(UID)
            )
            """
        )
        conn.execute("INSERT INTO Bids (UID) VALUES (1)")
        conn.execute("INSERT INTO Bids (UID) VALUES (2)")
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (10, 1)")
        conn.execute(
            "INSERT INTO BidSettings (UID, BidUID, BidPageSelectedUID) "
            "VALUES (20, 2, 10)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_bids("bid.mdb", ["1"]))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidPages").fetchone()[0], 0)
        self.assertEqual(
            conn.execute("SELECT BidUID FROM BidSettings WHERE UID = 20").fetchone()[0],
            2,
        )
        self.assertIsNone(
            conn.execute(
                "SELECT BidPageSelectedUID FROM BidSettings WHERE UID = 20"
            ).fetchone()[0]
        )

    def test_save_bid_selected_page_rejects_page_from_another_bid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute(
            """
            CREATE TABLE BidPages (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidSettings (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageSelectedUID INTEGER
            )
            """
        )
        conn.execute("INSERT INTO Bids (UID) VALUES (1)")
        conn.execute("INSERT INTO Bids (UID) VALUES (2)")
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (10, 1)")
        conn.execute(
            "INSERT INTO BidSettings (UID, BidUID, BidPageSelectedUID) "
            "VALUES (20, 2, NULL)"
        )
        self.assertFalse(
            _SqliteMdbOps(conn).save_bid_selected_page("bid.mdb", "2", "10")
        )
        self.assertIsNone(
            conn.execute(
                "SELECT BidPageSelectedUID FROM BidSettings WHERE UID = 20"
            ).fetchone()[0]
        )

    def test_delete_page_clears_bid_settings_selected_page_before_page_delete(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute(
            """
            CREATE TABLE BidPages (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidSettings (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID),
                BidPageSelectedUID INTEGER REFERENCES BidPages(UID)
            )
            """
        )
        conn.execute("INSERT INTO Bids (UID) VALUES (1)")
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (10, 1)")
        conn.execute(
            "INSERT INTO BidSettings (UID, BidUID, BidPageSelectedUID) "
            "VALUES (2, 1, 10)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["10"]))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidPages").fetchone()[0], 0)
        self.assertIsNone(
            conn.execute(
                "SELECT BidPageSelectedUID FROM BidSettings WHERE UID = 2"
            ).fetchone()[0]
        )

    def test_delete_page_removes_indexed_annotation_shape_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE BidPages (UID INTEGER PRIMARY KEY)")
        conn.execute(
            """
            CREATE TABLE BidAnnotationRects (
                UID INTEGER PRIMARY KEY,
                BidPageUID INTEGER,
                BidLayerUID INTEGER
            )
            """
        )
        conn.execute("INSERT INTO BidPages (UID) VALUES (10)")
        conn.execute(
            "INSERT INTO BidAnnotationRects (UID, BidPageUID, BidLayerUID) "
            "VALUES (20, 10, 30)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["10"]))
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidAnnotationRects").fetchone()[0],
            0,
        )
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidPages").fetchone()[0], 0)

    def test_delete_layer_clears_indexed_annotation_shape_layer_refs(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            """
            CREATE TABLE BidLayers (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                Sequence INTEGER,
                IsTemplate INTEGER,
                IsLocked INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidAnnotationRects (
                UID INTEGER PRIMARY KEY,
                BidLayerUID INTEGER
            )
            """
        )
        conn.execute(
            "INSERT INTO BidLayers "
            "(UID, BidUID, Sequence, IsTemplate, IsLocked) VALUES (30, 1, 1, 0, 0)"
        )
        conn.execute(
            "INSERT INTO BidLayers "
            "(UID, BidUID, Sequence, IsTemplate, IsLocked) VALUES (31, 1, 2, 0, 0)"
        )
        conn.execute(
            "INSERT INTO BidAnnotationRects (UID, BidLayerUID) VALUES (20, 30)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_layer("bid.mdb", "30"))
        self.assertIsNone(
            conn.execute(
                "SELECT BidLayerUID FROM BidAnnotationRects WHERE UID = 20"
            ).fetchone()[0]
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidLayers").fetchone()[0], 1
        )

    def test_delete_condition_folder_refuses_folder_used_by_conditions(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "CREATE TABLE BidConditionFolders (UID INTEGER PRIMARY KEY, Name TEXT)"
        )
        conn.execute(
            """
            CREATE TABLE BidConditions (
                UID INTEGER PRIMARY KEY,
                BidConditionFolderUID INTEGER REFERENCES BidConditionFolders(UID)
            )
            """
        )
        conn.execute("INSERT INTO BidConditionFolders (UID, Name) VALUES (1, 'Used')")
        conn.execute(
            "INSERT INTO BidConditions (UID, BidConditionFolderUID) VALUES (10, 1)"
        )
        with self.assertLogs("test", level="WARNING"):
            self.assertFalse(
                _SqliteMdbOps(conn).delete_condition_folders("bid.mdb", ["1"])
            )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidConditionFolders").fetchone()[0],
            1,
        )

    def test_delete_condition_folder_allows_unused_folder(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "CREATE TABLE BidConditionFolders (UID INTEGER PRIMARY KEY, Name TEXT)"
        )
        conn.execute(
            """
            CREATE TABLE BidConditions (
                UID INTEGER PRIMARY KEY,
                BidConditionFolderUID INTEGER REFERENCES BidConditionFolders(UID)
            )
            """
        )
        conn.execute("INSERT INTO BidConditionFolders (UID, Name) VALUES (1, 'Unused')")
        self.assertTrue(_SqliteMdbOps(conn).delete_condition_folders("bid.mdb", ["1"]))
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidConditionFolders").fetchone()[0],
            0,
        )

    def test_save_condition_types_refuses_type_used_by_conditions(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE CdnTypes (UID INTEGER PRIMARY KEY, Name TEXT)")
        conn.execute(
            """
            CREATE TABLE BidConditions (
                UID INTEGER PRIMARY KEY,
                CdnTypeUID INTEGER REFERENCES CdnTypes(UID)
            )
            """
        )
        conn.execute("INSERT INTO CdnTypes (UID, Name) VALUES (1, 'Used')")
        conn.execute("INSERT INTO BidConditions (UID, CdnTypeUID) VALUES (10, 1)")
        with self.assertLogs("test", level="WARNING"):
            result = _SqliteMdbOps(conn).save_condition_types(
                "bid.mdb", {"deleted_uids": ["1"]}
            )
        self.assertIsNone(result)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM CdnTypes").fetchone()[0], 1)

    def test_save_condition_types_allows_unused_type_delete(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE CdnTypes (UID INTEGER PRIMARY KEY, Name TEXT)")
        conn.execute(
            """
            CREATE TABLE BidConditions (
                UID INTEGER PRIMARY KEY,
                CdnTypeUID INTEGER REFERENCES CdnTypes(UID)
            )
            """
        )
        conn.execute("INSERT INTO CdnTypes (UID, Name) VALUES (1, 'Unused')")
        result = _SqliteMdbOps(conn).save_condition_types(
            "bid.mdb", {"deleted_uids": ["1"]}
        )
        self.assertEqual(result, {})
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM CdnTypes").fetchone()[0], 0)

    def test_save_condition_types_preflights_complete_delete_batch(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE CdnTypes (UID INTEGER PRIMARY KEY, Name TEXT)")
        conn.execute(
            """
            CREATE TABLE BidConditions (
                UID INTEGER PRIMARY KEY,
                CdnTypeUID INTEGER REFERENCES CdnTypes(UID)
            )
            """
        )
        conn.execute("INSERT INTO CdnTypes (UID, Name) VALUES (1, 'Unused')")
        conn.execute("INSERT INTO CdnTypes (UID, Name) VALUES (2, 'Used')")
        conn.execute("INSERT INTO BidConditions (UID, CdnTypeUID) VALUES (10, 2)")
        with self.assertLogs("test", level="WARNING"):
            result = _SqliteMdbOps(conn).save_condition_types(
                "bid.mdb", {"deleted_uids": ["1", "2"]}
            )
        self.assertIsNone(result)
        self.assertEqual(
            conn.execute("SELECT UID FROM CdnTypes ORDER BY UID").fetchall(),
            [(1,), (2,)],
        )

    def test_save_condition_types_reports_schema_failure(self):
        conn = sqlite3.connect(":memory:")
        with self.assertLogs("test", level="ERROR"):
            result = _SqliteMdbOps(conn).save_condition_types(
                "bid.mdb", {"new": [{"uid": "new_0", "name": "Concrete"}]}
            )
        self.assertIsNone(result)

    def test_save_employees_returns_uid_map_for_new_employee(self):
        class EmployeeOps(_SqliteMdbOps):
            def _next_uid(self, cursor, table):
                cursor.execute(f"SELECT MAX([UID]) FROM [{table}]")
                row = cursor.fetchone()
                return int(row[0]) + 1 if row and row[0] is not None else 1

            def _execute_insert_values(
                self, cursor, _schema, table, values, _required_columns, _operation
            ):
                columns = list(values)
                column_sql = ", ".join(f"[{column}]" for column in columns)
                placeholders = ", ".join("?" for _column in columns)
                cursor.execute(
                    f"INSERT INTO [{table}] ({column_sql}) VALUES ({placeholders})",
                    *[values[column] for column in columns],
                )

        conn = sqlite3.connect(":memory:")
        conn.execute(
            """
            CREATE TABLE Employees (
                UID INTEGER PRIMARY KEY,
                EmployeeNo TEXT,
                FirstName TEXT,
                LastName TEXT,
                Address1 TEXT,
                Address2 TEXT,
                City TEXT,
                State TEXT,
                Zip TEXT,
                HomePhone TEXT,
                MobilePhone TEXT,
                EMail TEXT,
                PayClassUID INTEGER
            )
            """
        )
        conn.execute(
            "INSERT INTO Employees (UID, EmployeeNo, FirstName, LastName) "
            "VALUES (7, 'E1', 'Ava', 'Lee')"
        )
        employee = SimpleNamespace(
            uid="new_0",
            employee_no="E2",
            first_name="Mia",
            last_name="Ray",
            address1="",
            address2="",
            city="",
            state="",
            zip="",
            home_phone="",
            mobile_phone="",
            email="",
            pay_class_uid="",
        )
        result = EmployeeOps(conn).save_employees(
            "bid.mdb", {"new": [employee], "updated": [], "deleted_uids": []}
        )
        self.assertEqual(result, {"new_0": "8"})
        inserted = conn.execute(
            "SELECT EmployeeNo, FirstName, LastName FROM Employees WHERE UID=8"
        ).fetchone()
        self.assertEqual(inserted, ("E2", "Mia", "Ray"))

    def test_delete_parent_takeoff_clears_child_parent_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            """
            CREATE TABLE BidTakeoffs (
                UID INTEGER PRIMARY KEY,
                ParentUID INTEGER
            )
            """
        )
        conn.execute("INSERT INTO BidTakeoffs (UID, ParentUID) VALUES (1, NULL)")
        conn.execute("INSERT INTO BidTakeoffs (UID, ParentUID) VALUES (2, 1)")
        self.assertTrue(_SqliteMdbOps(conn).delete_takeoffs("bid.mdb", ["1"]))
        child = conn.execute(
            "SELECT ParentUID FROM BidTakeoffs WHERE UID = 2"
        ).fetchone()
        self.assertIsNone(child[0])

    def test_delete_takeoff_removes_annotations_linked_by_either_endpoint(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            """
            CREATE TABLE BidTakeoffs (
                UID INTEGER PRIMARY KEY,
                ParentUID INTEGER
            )
            """
        )
        conn.executemany(
            "INSERT INTO BidTakeoffs (UID, ParentUID) VALUES (?, NULL)",
            ((1,), (2,), (3,)),
        )
        for index, table in enumerate(TAKEOFF_REFERENCE_TABLES, start=1):
            conn.execute(
                f"""
                CREATE TABLE [{table}] (
                    UID INTEGER PRIMARY KEY,
                    BidTakeoffFromUID INTEGER,
                    BidTakeoffToUID INTEGER
                )
                """
            )
            conn.execute(
                f"""
                INSERT INTO [{table}]
                    (UID, BidTakeoffFromUID, BidTakeoffToUID)
                VALUES (?, 1, 2)
                """,
                (index,),
            )
        self.assertTrue(_SqliteMdbOps(conn).delete_takeoffs("bid.mdb", ["2"]))
        self.assertEqual(
            conn.execute("SELECT UID FROM BidTakeoffs ORDER BY UID").fetchall(),
            [(1,), (3,)],
        )
        for table in TAKEOFF_REFERENCE_TABLES:
            with self.subTest(table=table):
                self.assertEqual(
                    conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0],
                    0,
                )

    def test_takeoff_bulk_uid_normalization_deduplicates_in_order(self):
        ops = _RecordingTakeoffOps()
        self.assertEqual(
            ops._normalize_int_uids(["2", 1, "2", "003"], "takeoff"),
            [2, 1, 3],
        )
        with self.assertRaises(ValueError):
            ops._normalize_int_uids(["1", "bad"], "takeoff")
        with self.assertRaises(ValueError):
            ops._normalize_int_uids("123", "takeoff")

    def test_empty_takeoff_area_assignment_does_not_open_connection(self):
        ops = _RecordingTakeoffOps()
        self.assertTrue(ops.save_takeoffs_area("bid.mdb", [], "1"))
        self.assertEqual(ops.connection_count, 0)
        self.assertEqual(ops.executions, [])

    def test_unassigned_area_assignment_writes_null_for_single_takeoff(self):
        ops = _RecordingTakeoffOps()
        self.assertTrue(ops.save_takeoffs_area("bid.mdb", ["1"], "0"))
        self.assertEqual(ops.commits, 1)
        self.assertEqual(ops.rollbacks, 0)
        self.assertEqual(len(ops.executions), 1)
        query, params = ops.executions[0]
        self.assertEqual(
            query,
            "UPDATE [BidTakeoffs] SET [BidAreaUID]=? WHERE [UID]=?",
        )
        self.assertEqual(params, (None, 1))

    def test_small_takeoff_area_assignment_uses_one_chunked_statement(self):
        ops = _RecordingTakeoffOps()
        self.assertTrue(ops.save_takeoffs_area("bid.mdb", ["1", "2", "3"], "7"))
        self.assertEqual(ops.connection_count, 1)
        self.assertEqual(ops.commits, 1)
        self.assertEqual(len(ops.executions), 1)
        query, params = ops.executions[0]
        self.assertEqual(
            query,
            "UPDATE [BidTakeoffs] SET [BidAreaUID]=? " "WHERE [UID] IN (?,?,?)",
        )
        self.assertEqual(params, (7, 1, 2, 3))

    def test_large_takeoff_area_assignment_uses_access_safe_chunks(self):
        ops = _RecordingTakeoffOps()
        takeoff_uids = [str(uid) for uid in range(1, 302)]
        self.assertTrue(ops.save_takeoffs_area("bid.mdb", takeoff_uids, "7"))
        self.assertEqual(ops.connection_count, 1)
        self.assertEqual(ops.commits, 1)
        self.assertEqual(ops.rollbacks, 0)
        self.assertEqual(len(ops.executions), 7)
        self.assertTrue(
            all(
                query.startswith("UPDATE [BidTakeoffs] SET [BidAreaUID]=?")
                for query, _params in ops.executions
            )
        )
        self.assertTrue(all(len(params) <= 51 for _query, params in ops.executions))
        self.assertEqual(ops.executions[0][1], tuple([7] + list(range(1, 51))))

    def test_condition_and_negative_updates_share_chunked_takeoff_path(self):
        condition_ops = _RecordingTakeoffOps()
        negative_ops = _RecordingTakeoffOps()
        takeoff_uids = [str(uid) for uid in range(1, 102)]
        self.assertTrue(
            condition_ops.save_takeoffs_condition("bid.mdb", takeoff_uids, "22")
        )
        self.assertTrue(
            negative_ops.set_takeoffs_negative("bid.mdb", takeoff_uids, True)
        )
        self.assertEqual(len(condition_ops.executions), 3)
        self.assertEqual(len(negative_ops.executions), 3)
        self.assertTrue(
            all(
                query.startswith("UPDATE [BidTakeoffs] SET [BidConditionUID]=?")
                for query, _params in condition_ops.executions
            )
        )
        self.assertTrue(
            all(
                query.startswith("UPDATE [BidTakeoffs] SET [IsNegativeQuantity]=?")
                for query, _params in negative_ops.executions
            )
        )

    def test_takeoff_bulk_update_failure_rolls_back_all_chunks(self):
        ops = _RecordingTakeoffOps(fail_on_execute=2)
        with self.assertLogs("tests.recording_takeoff_ops", level="ERROR"):
            self.assertFalse(
                ops.save_takeoffs_area(
                    "bid.mdb", [str(uid) for uid in range(1, 102)], "3"
                )
            )
        self.assertEqual(ops.commits, 0)
        self.assertEqual(ops.rollbacks, 1)
        self.assertEqual(ops.connection_count, 1)

    def test_takeoff_bulk_update_hy001_retries_row_by_row_fresh_transaction(self):
        ops = _RecordingTakeoffOps(fail_once_hy001=True)
        with self.assertLogs("tests.recording_takeoff_ops", level="WARNING"):
            self.assertTrue(ops.save_takeoffs_area("bid.mdb", ["1", "2", "3"], "9"))
        self.assertEqual(ops.connection_count, 2)
        self.assertEqual(ops.rollbacks, 1)
        self.assertEqual(ops.commits, 1)
        retry_queries = [query for query, _params in ops.executions[1:]]
        self.assertEqual(
            retry_queries,
            [
                "UPDATE [BidTakeoffs] SET [BidAreaUID]=? WHERE [UID]=?",
                "UPDATE [BidTakeoffs] SET [BidAreaUID]=? WHERE [UID]=?",
                "UPDATE [BidTakeoffs] SET [BidAreaUID]=? WHERE [UID]=?",
            ],
        )

    def test_delete_takeoffs_chunks_references_parent_cleanup_and_final_delete(self):
        schema = _RecordingSchema(
            {
                "BidTakeoffs": {"UID", "ParentUID"},
                "BidDimensions": {"BidTakeoffFromUID"},
                "BidPercents": {"BidTakeoffUID"},
            }
        )
        ops = _RecordingTakeoffOps(schema=schema)
        self.assertTrue(
            ops.delete_takeoffs("bid.mdb", [str(uid) for uid in range(1, 102)])
        )
        self.assertEqual(ops.connection_count, 1)
        self.assertEqual(ops.commits, 1)
        self.assertEqual(ops.rollbacks, 0)
        self.assertEqual(len(ops.executions), 12)
        self.assertEqual(
            [len(params) for _query, params in ops.executions],
            [50, 50, 1, 50, 50, 1, 51, 51, 2, 50, 50, 1],
        )
        self.assertEqual(
            [query.split(" WHERE ")[0] for query, _params in ops.executions],
            [
                "DELETE FROM [BidDimensions]",
                "DELETE FROM [BidDimensions]",
                "DELETE FROM [BidDimensions]",
                "DELETE FROM [BidPercents]",
                "DELETE FROM [BidPercents]",
                "DELETE FROM [BidPercents]",
                "UPDATE [BidTakeoffs] SET [ParentUID]=?",
                "UPDATE [BidTakeoffs] SET [ParentUID]=?",
                "UPDATE [BidTakeoffs] SET [ParentUID]=?",
                "DELETE FROM [BidTakeoffs]",
                "DELETE FROM [BidTakeoffs]",
                "DELETE FROM [BidTakeoffs]",
            ],
        )

    def test_static_mdb_lookup_tables_are_immutable(self):
        self.assertIsInstance(
            AnnotationOperationsMixin._ANNOTATION_TABLE, MappingProxyType
        )
        self.assertIsInstance(
            ConditionOperationsMixin._FIELD_TO_COLUMN, MappingProxyType
        )
        self.assertIsInstance(PageOperationsMixin._POSITION_TABLES, tuple)

    def test_named_view_rename_writes_bid_named_views_name_only(self):
        class FakeSchema:
            def optional_table_missing(self, _table):
                return False

        class FakeCursor:
            def __init__(self):
                self.calls = []

            def execute(self, sql, *params):
                self.calls.append((sql, params))

        class FakeConnection:
            def __init__(self):
                self.cursor_instance = FakeCursor()

            def cursor(self):
                return self.cursor_instance

        class FakeWriter(AnnotationOperationsMixin):
            def __init__(self):
                self.connection = FakeConnection()
                self.required_columns = []
                self.logger = logging.getLogger("test")

            @contextmanager
            def _connection(self, _db_path):
                yield self.connection

            def _schema(self, _conn):
                return FakeSchema()

            def _require_write_columns(self, _schema, table, columns):
                self.required_columns.append((table, columns))

            @staticmethod
            def _record_caught_mutation_error(_exc):
                return False

        writer = FakeWriter()
        self.assertTrue(
            writer.save_annotation_text_properties(
                "job.mdb",
                [("42", "namedview", {"Text": "New View"})],
            )
        )
        self.assertEqual(writer.required_columns, [("BidNamedViews", ("UID", "Name"))])
        sql, params = writer.connection.cursor_instance.calls[0]
        self.assertIn("UPDATE [BidNamedViews] SET [Name]=?", sql)
        self.assertEqual(params, ("New View", 42))


if __name__ == "__main__":
    unittest.main()
