import logging
import sqlite3
import subprocess
import tempfile
import threading
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
from ost_visualizer.infrastructure.mdb.components.project_operations import (
    ProjectOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.settings_operations import (
    SettingsOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.settings_reader import (
    SettingsReaderMixin,
)
from ost_visualizer.infrastructure.mdb.components.takeoff_operations import (
    TakeoffOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.schema_contract import DEFAULT_LAYER_ROWS
from ost_visualizer.infrastructure.services.license_validation_scheduler import (
    LicenseValidationScheduler,
)
from ost_visualizer.domain.entities.area import BidArea, BidAreaChangeset
from ost_visualizer.application.dtos.create_condition_spec_dto import (
    CreateConditionSpec,
)
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.application.dtos.update_condition_dto import UpdateConditionDto


class _SqliteCursorWrapper:
    def __init__(self, connection):
        self._connection = connection
        self._cursor = None

    def execute(self, query, *params):
        self._cursor = self._connection.execute(query, params)

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def fetchone(self):
        if self._cursor is None:
            return None
        row = self._cursor.fetchone()
        if row is None or self._cursor.description is None:
            return row
        columns = [description[0] for description in self._cursor.description]
        return _SqliteRow(columns, row)

    def fetchall(self):
        if self._cursor is None:
            return []
        rows = self._cursor.fetchall()
        if self._cursor.description is None:
            return rows
        columns = [description[0] for description in self._cursor.description]
        return [_SqliteRow(columns, row) for row in rows]

    @property
    def rowcount(self):
        return self._cursor.rowcount if self._cursor is not None else -1

    @property
    def description(self):
        return self._cursor.description if self._cursor is not None else None

    @property
    def connection(self):
        return self._connection


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

    def require_column(self, table_name, column_name):
        if not self.column_exists(table_name, column_name):
            raise RuntimeError(f"Missing {table_name}.{column_name}")

    def get_columns(self, table_name):
        return {
            row[1]
            for row in self._connection.execute(f"PRAGMA table_info({table_name})")
        }

    def optional_column(self, table_name, column_name, default_sql):
        if self.column_exists(table_name, column_name):
            return f"[{column_name}]"
        return f"{default_sql} AS [{column_name}]"

    def order_by_existing(self, table_name, columns, fallback):
        existing = [
            column for column in columns if self.column_exists(table_name, column)
        ]
        return ", ".join(f"[{column}]" for column in existing) or fallback

    @staticmethod
    def log_optional_write_skip(_table, _column, _operation):
        pass


class _SqliteMdbOps(
    AccessBulkWriteMixin,
    BidOperationsMixin,
    ConditionOperationsMixin,
    ConditionFolderOperationsMixin,
    LayerOperationsMixin,
    ProjectOperationsMixin,
    SettingsOperationsMixin,
    PageOperationsMixin,
    TakeoffOperationsMixin,
):
    logger = logging.getLogger("test")
    _normalize_display_size = staticmethod(MdbReader._normalize_display_size)

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


class _SqliteDuplicateOps(_SqliteMdbOps):
    def _execute_insert_values(
        self, cursor, schema, table, values, _required, _operation
    ):
        persisted = {
            column: value
            for column, value in values.items()
            if schema.column_exists(table, column)
        }
        columns = list(persisted)
        placeholders = ", ".join("?" for _column in columns)
        cursor.execute(
            f"INSERT INTO [{table}] "
            f"({', '.join(f'[{column}]' for column in columns)}) "
            f"VALUES ({placeholders})",
            *(persisted[column] for column in columns),
        )

    def _execute_update_values(
        self,
        cursor,
        schema,
        table,
        values,
        _required,
        where_sql,
        where_params,
        _operation,
    ):
        persisted = {
            column: value
            for column, value in values.items()
            if schema.column_exists(table, column)
        }
        if not persisted:
            return False
        columns = list(persisted)
        assignments = ", ".join(f"[{column}]=?" for column in columns)
        cursor.execute(
            f"UPDATE [{table}] SET {assignments} WHERE {where_sql}",
            *(persisted[column] for column in columns),
            *where_params,
        )
        return True


class _SqliteAnnotationOps(AnnotationOperationsMixin, _SqliteDuplicateOps):
    pass


class _RecordingSchema:
    def __init__(self, columns_by_table=None):
        self.columns_by_table = columns_by_table or {
            "BidTakeoffs": {
                "UID",
                "BidUID",
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
        self.validation_rows = []

    def execute(self, query, *params):
        if query.startswith("SELECT [UID], [BidUID] FROM ["):
            self.validation_rows = [(param, 1) for param in params]
            return
        if query.startswith("SELECT [UID] FROM ["):
            self.validation_rows = [(param,) for param in params]
            return
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

    def fetchall(self):
        return list(self.validation_rows)


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

    def test_license_validation_scheduler_retains_in_flight_thread(self):
        task_started = threading.Event()
        release_task = threading.Event()

        def blocking_task():
            task_started.set()
            release_task.wait()

        scheduler = LicenseValidationScheduler(interval_seconds=0, task=blocking_task)
        scheduler.start()
        self.assertTrue(task_started.wait(timeout=1))
        thread = scheduler._thread
        with patch.object(threading.Thread, "join"):
            scheduler.stop()
        self.assertIs(scheduler._thread, thread)
        self.assertTrue(scheduler.is_running())
        scheduler.start()
        self.assertIs(scheduler._thread, thread)
        release_task.set()
        thread.join(timeout=1)
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

        def connect(_connection_string, autocommit=False):
            self.assertFalse(autocommit)
            return fake_connection

        database_creator.pyodbc.connect = connect
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

        def connect(_connection_string, autocommit=False):
            self.assertFalse(autocommit)
            return fake_connection

        database_creator.pyodbc.connect = connect
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
                pass

            def close(self):
                raise RuntimeError("cursor close failed")

        class FakeConnection:
            def __init__(self):
                self.closed = False

            def cursor(self):
                return FakeCursor()

            def commit(self):
                pass

            def rollback(self):
                raise AssertionError("successful schema should not roll back")

            def close(self):
                self.closed = True

        fake_connection = FakeConnection()
        original_connect = database_creator.pyodbc.connect

        def connect(_connection_string, autocommit=False):
            self.assertFalse(autocommit)
            return fake_connection

        database_creator.pyodbc.connect = connect
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

        def connect(_connection_string, autocommit=False):
            self.assertFalse(autocommit)
            return fake_connection

        database_creator.pyodbc.connect = connect
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

    def test_delete_bid_removes_legacy_annotation_linked_only_by_to_takeoff(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE BidTakeoffs (UID INTEGER PRIMARY KEY, BidUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidDimensions ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, BidPageUID INTEGER, "
            "BidTakeoffFromUID INTEGER, BidTakeoffToUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("INSERT INTO BidTakeoffs VALUES (10, 1)")
        conn.execute("INSERT INTO BidDimensions VALUES (20, NULL, NULL, NULL, 10)")
        self.assertTrue(_SqliteMdbOps(conn).delete_bids("bid.mdb", ["1"]))
        self.assertEqual(conn.execute("SELECT * FROM BidDimensions").fetchall(), [])
        self.assertEqual(conn.execute("SELECT * FROM BidTakeoffs").fetchall(), [])
        self.assertEqual(conn.execute("SELECT * FROM Bids").fetchall(), [])

    def test_delete_project_clears_deleted_bid_restore_reference(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidProjects (UID INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE Bids ("
            "UID INTEGER PRIMARY KEY, BidProjectUID INTEGER, "
            "OrigBidProjectUID INTEGER)"
        )
        conn.executemany("INSERT INTO BidProjects VALUES (?)", ((1,), (2,)))
        conn.execute("INSERT INTO Bids VALUES (10, 2, 1)")
        self.assertTrue(_SqliteMdbOps(conn).delete_projects("bid.mdb", ["1"]))
        self.assertEqual(
            conn.execute(
                "SELECT BidProjectUID, OrigBidProjectUID FROM Bids WHERE UID=10"
            ).fetchone(),
            (2, None),
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidProjects ORDER BY UID").fetchall(),
            [(2,)],
        )

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

    def test_save_bid_selected_page_rejects_multiple_settings_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER PRIMARY KEY, BidUID INTEGER)")
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
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (10, 1)")
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (11, 1)")
        conn.execute(
            "INSERT INTO BidSettings (UID, BidUID, BidPageSelectedUID) "
            "VALUES (20, 1, 10)"
        )
        conn.execute(
            "INSERT INTO BidSettings (UID, BidUID, BidPageSelectedUID) "
            "VALUES (21, 1, 11)"
        )
        self.assertFalse(
            _SqliteMdbOps(conn).save_bid_selected_page("bid.mdb", "1", "11")
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidPageSelectedUID FROM BidSettings ORDER BY UID"
            ).fetchall(),
            [(20, 10), (21, 11)],
        )

    def test_save_bid_selected_page_creates_missing_legacy_settings_row(self):
        class Ops(_SqliteMdbOps):
            @staticmethod
            def _execute_insert_values(
                cursor,
                schema,
                table,
                values,
                required_columns,
                _operation,
            ):
                for column in required_columns:
                    if not schema.column_exists(table, column):
                        raise RuntimeError(f"Missing {table}.{column}")
                filtered = {
                    column: value
                    for column, value in values.items()
                    if schema.column_exists(table, column)
                }
                columns = tuple(filtered)
                cursor.execute(
                    f"INSERT INTO [{table}] "
                    f"({', '.join(f'[{column}]' for column in columns)}) "
                    f"VALUES ({', '.join('?' for _column in columns)})",
                    *(filtered[column] for column in columns),
                )

        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER PRIMARY KEY, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidSettings (" "BidUID INTEGER, BidPageSelectedUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids (UID) VALUES (1)")
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (10, 1)")
        self.assertTrue(Ops(conn).save_bid_selected_page("bid.mdb", "1", "10"))
        self.assertEqual(
            conn.execute(
                "SELECT BidUID, BidPageSelectedUID FROM BidSettings"
            ).fetchall(),
            [(1, 10)],
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

    def test_delete_page_clears_only_page_typed_cover_sheet_selection(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE Bids ("
            "UID INTEGER PRIMARY KEY, "
            "CoverSheetSelItemType INTEGER, "
            "CoverSheetSelItemUID INTEGER)"
        )
        conn.execute("CREATE TABLE BidPages (UID INTEGER PRIMARY KEY, BidUID INTEGER)")
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (10, 1)")
        conn.execute(
            "INSERT INTO Bids "
            "(UID, CoverSheetSelItemType, CoverSheetSelItemUID) "
            "VALUES (1, 1, 10)"
        )
        conn.execute(
            "INSERT INTO Bids "
            "(UID, CoverSheetSelItemType, CoverSheetSelItemUID) "
            "VALUES (2, 2, 10)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["10"]))
        rows = conn.execute(
            "SELECT UID, CoverSheetSelItemUID FROM Bids ORDER BY UID"
        ).fetchall()
        self.assertEqual(rows, [(1, None), (2, 10)])

    def test_delete_pages_preserves_conditions_uoms_and_remaining_takeoffs(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER PRIMARY KEY, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, UOM1 INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER PRIMARY KEY, BidPageUID INTEGER, BidConditionUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidPages (UID, BidUID) VALUES (?, 1)",
            ((10,), (11,), (12,)),
        )
        conn.executemany(
            "INSERT INTO BidConditions (UID, BidUID, UOM1) VALUES (?, 1, ?)",
            ((20, 7), (21, 9)),
        )
        conn.executemany(
            "INSERT INTO BidTakeoffs (UID, BidPageUID, BidConditionUID) "
            "VALUES (?, ?, ?)",
            (
                (30, 10, 20),
                (31, 11, 20),
                (32, 12, 21),
            ),
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["10", "12"]))
        self.assertEqual(
            conn.execute("SELECT UID, UOM1 FROM BidConditions ORDER BY UID").fetchall(),
            [(20, 7), (21, 9)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidPageUID, BidConditionUID FROM BidTakeoffs"
            ).fetchall(),
            [(31, 11, 20)],
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidPages ORDER BY UID").fetchall(),
            [(11,)],
        )

    def test_delete_page_removes_indexed_annotation_shape_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER PRIMARY KEY, BidUID INTEGER)")
        conn.execute(
            """
            CREATE TABLE BidAnnotationRects (
                UID INTEGER PRIMARY KEY,
                BidPageUID INTEGER,
                BidLayerUID INTEGER
            )
            """
        )
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (10, 1)")
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

    def test_delete_page_removes_all_ancillary_page_dependents(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER PRIMARY KEY, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidTypGroupViews ("
            "UID INTEGER PRIMARY KEY, BidPageUID INTEGER REFERENCES BidPages(UID))"
        )
        conn.execute(
            "CREATE TABLE AffectDPCTypGroupViews ("
            "UID INTEGER PRIMARY KEY, BidTypGroupViewUID INTEGER "
            "REFERENCES BidTypGroupViews(UID))"
        )
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (10, 1)")
        for table in (
            "BidPercents",
            "BidTakeoffTotals",
            "BidLaborCostCodeTotals",
            "BidTypicalGroupTotals",
            "Boost",
            "DPCCalcFilter",
        ):
            conn.execute(
                f"CREATE TABLE {table} (UID INTEGER PRIMARY KEY, "
                "BidPageUID INTEGER REFERENCES BidPages(UID))"
            )
            conn.execute(
                f"INSERT INTO {table} (UID, BidPageUID) VALUES (?, 10)",
                (100 + len(table),),
            )
        conn.execute("INSERT INTO BidTypGroupViews (UID, BidPageUID) VALUES (20, 10)")
        conn.execute(
            "INSERT INTO AffectDPCTypGroupViews "
            "(UID, BidTypGroupViewUID) VALUES (30, 20)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["10"]))
        for table in (
            "AffectDPCTypGroupViews",
            "BidTypGroupViews",
            "BidPercents",
            "BidTakeoffTotals",
            "BidLaborCostCodeTotals",
            "BidTypicalGroupTotals",
            "Boost",
            "DPCCalcFilter",
            "BidPages",
        ):
            with self.subTest(table=table):
                self.assertEqual(
                    conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
                )

    def test_delete_condition_removes_all_ancillary_condition_dependents(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidConditions (UID INTEGER PRIMARY KEY, BidUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidLaborActivity ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, BidConditionUID INTEGER "
            "REFERENCES BidConditions(UID))"
        )
        conn.execute(
            "CREATE TABLE BidPercents ("
            "UID INTEGER PRIMARY KEY, BidLaborActivityUID INTEGER "
            "REFERENCES BidLaborActivity(UID))"
        )
        conn.execute(
            "CREATE TABLE BidTypGroupViews ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, BidConditionUID INTEGER "
            "REFERENCES BidConditions(UID))"
        )
        conn.execute(
            "CREATE TABLE AffectDPCTypGroupViews ("
            "UID INTEGER PRIMARY KEY, BidTypGroupViewUID INTEGER "
            "REFERENCES BidTypGroupViews(UID))"
        )
        conn.execute("INSERT INTO BidConditions (UID, BidUID) VALUES (10, 1)")
        for table in ("BidTakeoffTotals", "BidTypicalGroupTotals"):
            conn.execute(
                f"CREATE TABLE {table} (UID INTEGER PRIMARY KEY, BidUID INTEGER, "
                "BidConditionUID INTEGER REFERENCES BidConditions(UID))"
            )
            conn.execute(
                f"INSERT INTO {table} (UID, BidUID, BidConditionUID) "
                "VALUES (?, 1, 10)",
                (100 + len(table),),
            )
        conn.execute(
            "INSERT INTO BidLaborActivity "
            "(UID, BidUID, BidConditionUID) VALUES (20, 1, 10)"
        )
        conn.execute(
            "INSERT INTO BidPercents (UID, BidLaborActivityUID) VALUES (30, 20)"
        )
        conn.execute(
            "INSERT INTO BidTypGroupViews "
            "(UID, BidUID, BidConditionUID) VALUES (40, 1, 10)"
        )
        conn.execute(
            "INSERT INTO AffectDPCTypGroupViews "
            "(UID, BidTypGroupViewUID) VALUES (50, 40)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_conditions("bid.mdb", "1", ["10"]))
        for table in (
            "BidPercents",
            "BidLaborActivity",
            "AffectDPCTypGroupViews",
            "BidTypGroupViews",
            "BidTakeoffTotals",
            "BidTypicalGroupTotals",
            "BidConditions",
        ):
            with self.subTest(table=table):
                self.assertEqual(
                    conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
                )

    def test_delete_area_removes_all_ancillary_area_dependents(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidAreas (UID INTEGER PRIMARY KEY, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidAreaTranslations ("
            "UID INTEGER PRIMARY KEY, MasterAreaUID INTEGER REFERENCES BidAreas(UID), "
            "TranslateAreaUID INTEGER REFERENCES BidAreas(UID))"
        )
        conn.execute("INSERT INTO BidAreas (UID, BidUID) VALUES (10, 1)")
        for table in (
            "BidTakeoffTotals",
            "BidLaborCostCodeTotals",
            "BidTypicalGroupTotals",
        ):
            conn.execute(
                f"CREATE TABLE {table} (UID INTEGER PRIMARY KEY, "
                "BidAreaUID INTEGER REFERENCES BidAreas(UID))"
            )
            conn.execute(
                f"INSERT INTO {table} (UID, BidAreaUID) VALUES (?, 10)",
                (100 + len(table),),
            )
        conn.execute(
            "INSERT INTO BidAreaTranslations "
            "(UID, MasterAreaUID, TranslateAreaUID) VALUES (20, 10, 10)"
        )
        result = _SqliteMdbOps(conn).save_bid_areas(
            "bid.mdb",
            "1",
            BidAreaChangeset(new=[], updated=[], deleted_uids=["10"]),
        )
        self.assertEqual(result, {})
        for table in (
            "BidAreaTranslations",
            "BidTakeoffTotals",
            "BidLaborCostCodeTotals",
            "BidTypicalGroupTotals",
            "BidAreas",
        ):
            with self.subTest(table=table):
                self.assertEqual(
                    conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
                )

    def test_condition_delete_clears_surviving_takeoff_self_references(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
            "ParentUID INTEGER, TypGroupTakeoffUID INTEGER, "
            "TypPageTakeoffUID INTEGER, TypGroupMarkerUID INTEGER)"
        )
        conn.executemany("INSERT INTO BidConditions VALUES (?, 1)", ((10,), (11,)))
        conn.executemany(
            "INSERT INTO BidTakeoffs VALUES (?, 1, ?, ?, ?, ?, ?)",
            ((70, 10, None, None, None, None), (80, 11, 70, 70, 70, 70)),
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_conditions("bid.mdb", "1", ["10"]))
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID, TypGroupTakeoffUID, TypPageTakeoffUID, "
                "TypGroupMarkerUID FROM BidTakeoffs"
            ).fetchall(),
            [(80, None, None, None, None)],
        )

    def test_condition_delete_removes_condition_user_companion_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditionUser ("
            "UID INTEGER, BidUID INTEGER, ConditionUID INTEGER)"
        )
        conn.execute("INSERT INTO BidConditions VALUES (10, 1)")
        conn.execute("INSERT INTO BidConditionUser VALUES (20, 1, 10)")
        self.assertTrue(_SqliteMdbOps(conn).delete_conditions("bid.mdb", "1", ["10"]))
        self.assertEqual(conn.execute("SELECT * FROM BidConditionUser").fetchall(), [])
        self.assertEqual(conn.execute("SELECT * FROM BidConditions").fetchall(), [])

    def test_condition_delete_removes_annotations_linked_by_to_takeoff(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidDimensions ("
            "UID INTEGER, BidTakeoffFromUID INTEGER, BidTakeoffToUID INTEGER)"
        )
        conn.executemany("INSERT INTO BidConditions VALUES (?, 1)", ((10,), (11,)))
        conn.executemany(
            "INSERT INTO BidTakeoffs VALUES (?, 1, ?)", ((70, 10), (80, 11))
        )
        conn.execute("INSERT INTO BidDimensions VALUES (90, 80, 70)")
        self.assertTrue(_SqliteMdbOps(conn).delete_conditions("bid.mdb", "1", ["10"]))
        self.assertEqual(conn.execute("SELECT * FROM BidDimensions").fetchall(), [])
        self.assertEqual(
            conn.execute("SELECT UID FROM BidTakeoffs").fetchall(), [(80,)]
        )

    def test_area_save_rejects_parent_cycle_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidAreas ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT, "
            "Sequence INTEGER, GUID TEXT)"
        )
        conn.executemany(
            "INSERT INTO BidAreas VALUES (?, 1, ?, ?, 0, '')",
            ((7, None, "First"), (8, 7, "Second")),
        )
        result = _SqliteDuplicateOps(conn).save_bid_areas(
            "malformed.mdb",
            "1",
            BidAreaChangeset(
                new=[],
                updated=[BidArea("7", "1", "8", "Changed", 0)],
                deleted_uids=[],
            ),
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID, Name FROM BidAreas ORDER BY UID"
            ).fetchall(),
            [(7, None, "First"), (8, 7, "Second")],
        )

    def test_area_save_rejects_cross_bid_parent_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidAreas ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT, "
            "Sequence INTEGER, GUID TEXT)"
        )
        conn.executemany(
            "INSERT INTO BidAreas VALUES (?, ?, NULL, ?, 0, '')",
            ((7, 1, "Source"), (8, 2, "Other bid")),
        )
        result = _SqliteDuplicateOps(conn).save_bid_areas(
            "malformed.mdb",
            "1",
            BidAreaChangeset(
                new=[],
                updated=[BidArea("7", "1", "8", "Changed", 0)],
                deleted_uids=[],
            ),
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute("SELECT ParentUID, Name FROM BidAreas WHERE UID=7").fetchone(),
            (None, "Source"),
        )

    def test_area_save_rejects_deleting_parent_with_surviving_child(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidAreas ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT, "
            "Sequence INTEGER, GUID TEXT)"
        )
        conn.executemany(
            "INSERT INTO BidAreas VALUES (?, 1, ?, ?, 0, '')",
            ((7, None, "Parent"), (8, 7, "Child")),
        )
        result = _SqliteDuplicateOps(conn).save_bid_areas(
            "malformed.mdb",
            "1",
            BidAreaChangeset(new=[], updated=[], deleted_uids=["7"]),
        )
        self.assertEqual(result, {})
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidAreas").fetchone()[0], 2)

    def test_legacy_area_save_rejects_unpersistable_hierarchy(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidAreas ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, Sequence INTEGER, GUID TEXT)"
        )
        conn.executemany(
            "INSERT INTO BidAreas VALUES (?, 1, ?, 0, '')",
            ((7, "First"), (8, "Second")),
        )
        result = _SqliteDuplicateOps(conn).save_bid_areas(
            "legacy.mdb",
            "1",
            BidAreaChangeset(
                new=[],
                updated=[BidArea("8", "1", "7", "Changed", 0)],
                deleted_uids=[],
            ),
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute("SELECT UID, Name FROM BidAreas ORDER BY UID").fetchall(),
            [(7, "First"), (8, "Second")],
        )

    def test_legacy_area_save_accepts_flat_update_without_parent_column(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidAreas ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, Sequence INTEGER, GUID TEXT)"
        )
        conn.execute("INSERT INTO BidAreas VALUES (7, 1, 'Before', 0, '')")
        result = _SqliteDuplicateOps(conn).save_bid_areas(
            "legacy.mdb",
            "1",
            BidAreaChangeset(
                new=[],
                updated=[BidArea("7", "1", "", "After", 0)],
                deleted_uids=[],
            ),
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute("SELECT Name FROM BidAreas WHERE UID=7").fetchone()[0],
            "After",
        )

    def test_page_delete_clears_master_page_and_cross_page_comment_parent(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, MasterPageUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidComments ("
            "UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, "
            "ParentCommentUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidPages VALUES (?, ?, ?)",
            ((7, 1, None), (8, 1, 7), (9, 2, 7)),
        )
        conn.executemany(
            "INSERT INTO BidComments VALUES (?, 1, ?, ?)",
            ((70, 7, None), (80, 8, 70)),
        )
        conn.execute("INSERT INTO BidComments VALUES (90, 2, 9, 70)")
        self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["7"]))
        self.assertEqual(
            conn.execute(
                "SELECT UID, MasterPageUID FROM BidPages ORDER BY UID"
            ).fetchall(),
            [(8, None), (9, 7)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentCommentUID FROM BidComments ORDER BY UID"
            ).fetchall(),
            [(80, None), (90, 70)],
        )

    def test_page_delete_clears_surviving_takeoff_self_references(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, "
            "ParentUID INTEGER, TypGroupTakeoffUID INTEGER, "
            "TypPageTakeoffUID INTEGER, TypGroupMarkerUID INTEGER)"
        )
        conn.executemany("INSERT INTO BidPages VALUES (?, ?)", ((7, 1), (8, 1), (9, 2)))
        conn.executemany(
            "INSERT INTO BidTakeoffs VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                (70, 1, 7, None, None, None, None),
                (80, 1, 8, 70, 70, 70, 70),
                (90, 2, 9, 70, 70, 70, 70),
            ),
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["7"]))
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID, TypGroupTakeoffUID, TypPageTakeoffUID, "
                "TypGroupMarkerUID FROM BidTakeoffs"
            ).fetchall(),
            [(80, None, None, None, None), (90, 70, 70, 70, 70)],
        )

    def test_page_delete_removes_annotations_linked_by_to_takeoff(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, BidPageUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidDimensions ("
            "UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, "
            "BidTakeoffFromUID INTEGER, BidTakeoffToUID INTEGER)"
        )
        conn.executemany("INSERT INTO BidPages VALUES (?, 1)", ((7,), (8,)))
        conn.executemany("INSERT INTO BidTakeoffs VALUES (?, 1, ?)", ((70, 7), (80, 8)))
        conn.execute("INSERT INTO BidDimensions VALUES (90, 1, 8, 80, 70)")
        self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["7"]))
        self.assertEqual(conn.execute("SELECT * FROM BidDimensions").fetchall(), [])
        self.assertEqual(
            conn.execute("SELECT UID FROM BidTakeoffs").fetchall(), [(80,)]
        )

    def test_self_reference_uid_allocation_prevents_late_binding(self):
        for table, reference_column in (
            ("BidPages", "MasterPageUID"),
            ("BidComments", "ParentCommentUID"),
        ):
            with self.subTest(table=table):
                conn = sqlite3.connect(":memory:")
                conn.execute(
                    f"CREATE TABLE {table} (UID INTEGER, {reference_column} INTEGER)"
                )
                conn.execute(f"INSERT INTO {table} VALUES (7, 8)")
                ops = _SqliteDuplicateOps(conn)
                self.assertEqual(
                    ops._next_uid_preserving_references(
                        _SqliteCursorWrapper(conn), ops._schema_ref, table
                    ),
                    9,
                )

    def test_area_insert_reserves_dangling_indirect_area_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidAreas ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT, "
            "Sequence INTEGER, GUID TEXT)"
        )
        conn.execute("CREATE TABLE BidTypAreaCounts (UID INTEGER, BidAreaUID INTEGER)")
        conn.execute("INSERT INTO BidAreas VALUES (7, 1, NULL, 'Existing', 1, '')")
        conn.execute("INSERT INTO BidTypAreaCounts VALUES (1, 8)")
        uid_map = _SqliteDuplicateOps(conn).save_bid_areas(
            "legacy.mdb",
            "1",
            BidAreaChangeset(
                new=[BidArea("new_0", "1", "", "New", 2)],
                updated=[],
                deleted_uids=[],
            ),
        )
        self.assertEqual(uid_map, {"new_0": "9"})
        self.assertEqual(
            conn.execute("SELECT UID FROM BidAreas ORDER BY UID").fetchall(),
            [(7,), (9,)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM BidTypAreaCounts AS counts "
                "INNER JOIN BidAreas AS area ON counts.BidAreaUID=area.UID"
            ).fetchone()[0],
            0,
        )

    def test_delete_layer_clears_indexed_annotation_shape_layer_refs(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
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
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, Name TEXT)"
        )
        conn.execute(
            """
            CREATE TABLE BidConditions (
                UID INTEGER PRIMARY KEY,
                BidConditionFolderUID INTEGER REFERENCES BidConditionFolders(UID)
            )
            """
        )
        conn.execute(
            "INSERT INTO BidConditionFolders (UID, BidUID, Name) "
            "VALUES (1, 1, 'Used')"
        )
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
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, Name TEXT)"
        )
        conn.execute(
            """
            CREATE TABLE BidConditions (
                UID INTEGER PRIMARY KEY,
                BidConditionFolderUID INTEGER REFERENCES BidConditionFolders(UID)
            )
            """
        )
        conn.execute(
            "INSERT INTO BidConditionFolders (UID, BidUID, Name) "
            "VALUES (1, 1, 'Unused')"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_condition_folders("bid.mdb", ["1"]))
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidConditionFolders").fetchone()[0],
            0,
        )

    def test_delete_condition_folder_reparents_surviving_child_to_root(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        conn.execute("CREATE TABLE BidConditions (UID INTEGER PRIMARY KEY)")
        conn.executemany(
            "INSERT INTO BidConditionFolders VALUES (?, 1, ?, ?)",
            ((1, "Parent", None), (2, "Child", 1)),
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_condition_folders("bid.mdb", ["1"]))
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID FROM BidConditionFolders ORDER BY UID"
            ).fetchall(),
            [(2, None)],
        )

    def test_insert_condition_folder_rejects_missing_or_cross_bid_parent(self):
        for parent_rows in ((), ((7, 2),)):
            with self.subTest(parent_rows=parent_rows):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE Bids (UID INTEGER)")
                conn.execute("INSERT INTO Bids VALUES (1)")
                conn.execute(
                    "CREATE TABLE BidConditionFolders ("
                    "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, "
                    "Name TEXT, ExpandState INTEGER)"
                )
                conn.executemany(
                    "INSERT INTO BidConditionFolders "
                    "(UID, BidUID, Name) VALUES (?, ?, 'Other')",
                    parent_rows,
                )
                self.assertIsNone(
                    _SqliteDuplicateOps(conn).insert_condition_folder(
                        "malformed.mdb", "1", "Child", "7"
                    )
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT UID, BidUID, ParentUID FROM BidConditionFolders "
                        "WHERE BidUID=1"
                    ).fetchall(),
                    [],
                )

    def test_insert_condition_folder_accepts_same_bid_parent(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, "
            "Name TEXT, ExpandState INTEGER)"
        )
        conn.execute(
            "INSERT INTO BidConditionFolders (UID, BidUID, Name) "
            "VALUES (7, 1, 'Parent')"
        )
        self.assertEqual(
            _SqliteDuplicateOps(conn).insert_condition_folder(
                "valid.mdb", "1", "Child", "7"
            ),
            "8",
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, ParentUID FROM BidConditionFolders " "WHERE UID=8"
            ).fetchone(),
            (8, 1, 7),
        )

    def test_insert_condition_folder_rejects_parent_when_schema_is_flat(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, ExpandState INTEGER)"
        )
        conn.execute("INSERT INTO BidConditionFolders VALUES (7, 1, 'Parent', -1)")
        self.assertIsNone(
            _SqliteDuplicateOps(conn).insert_condition_folder(
                "legacy.mdb", "1", "Child", "7"
            )
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, Name FROM BidConditionFolders ORDER BY UID"
            ).fetchall(),
            [(7, 1, "Parent")],
        )
        self.assertEqual(
            _SqliteDuplicateOps(conn).insert_condition_folder(
                "legacy.mdb", "1", "Root", None
            ),
            "8",
        )

    def test_condition_folder_insert_reserves_dangling_parent_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, "
            "Name TEXT, ExpandState INTEGER)"
        )
        conn.execute("INSERT INTO BidConditionFolders VALUES (7, 1, 8, 'Orphan', -1)")
        self.assertEqual(
            _SqliteDuplicateOps(conn).insert_condition_folder(
                "legacy.mdb", "1", "Unrelated", None
            ),
            "9",
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID FROM BidConditionFolders ORDER BY UID"
            ).fetchall(),
            [(7, 8), (9, None)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM BidConditionFolders AS child "
                "INNER JOIN BidConditionFolders AS parent "
                "ON child.ParentUID=parent.UID"
            ).fetchone()[0],
            0,
        )

    def test_project_insert_does_not_claim_orphan_bid_project_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidProjects (UID INTEGER, Name TEXT)")
        conn.execute(
            "CREATE TABLE Bids (UID INTEGER, BidProjectUID INTEGER, JobName TEXT)"
        )
        conn.execute("INSERT INTO BidProjects VALUES (7, 'Existing')")
        conn.execute("INSERT INTO Bids VALUES (1, 8, 'Orphan')")
        new_uid = _SqliteDuplicateOps(conn).create_project("legacy.mdb", "New")
        self.assertEqual(new_uid, "9")
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM Bids AS bid "
                "INNER JOIN BidProjects AS project "
                "ON bid.BidProjectUID=project.UID"
            ).fetchone()[0],
            0,
        )

    def test_condition_duplicate_reserves_dangling_ancillary_condition_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER, BidUID INTEGER, GUID TEXT, RefNo INTEGER, Name TEXT)"
        )
        conn.execute(
            "CREATE TABLE BidTakeoffTotals (UID INTEGER, BidConditionUID INTEGER)"
        )
        conn.execute(
            "INSERT INTO BidConditions VALUES (7, 1, 'source-guid', 1, 'Source')"
        )
        conn.execute("INSERT INTO BidTakeoffTotals VALUES (1, 8)")
        new_uids = _SqliteDuplicateOps(conn).duplicate_conditions("bid.mdb", "1", ["7"])
        self.assertEqual(new_uids, ["9"])
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM BidTakeoffTotals AS totals "
                "INNER JOIN BidConditions AS conditions "
                "ON totals.BidConditionUID=conditions.UID"
            ).fetchone()[0],
            0,
        )

    def test_condition_duplicate_rejects_cross_bid_batch_before_insert(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER, BidUID INTEGER, GUID TEXT, RefNo INTEGER, Name TEXT)"
        )
        conn.executemany(
            "INSERT INTO BidConditions VALUES (?, ?, ?, 1, ?)",
            ((7, 1, "first-guid", "First"), (8, 2, "other-guid", "Other")),
        )
        result = _SqliteDuplicateOps(conn).duplicate_conditions(
            "malformed.mdb", "1", ["7", "8"]
        )
        self.assertEqual(result, [])
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID FROM BidConditions ORDER BY UID"
            ).fetchall(),
            [(7, 1), (8, 2)],
        )

    def test_condition_delete_rejects_cross_bid_batch_before_cascade(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER)"
        )
        conn.executemany("INSERT INTO BidConditions VALUES (?, ?)", ((7, 1), (8, 2)))
        conn.execute("INSERT INTO BidTakeoffs VALUES (70, 1, 7)")
        result = _SqliteDuplicateOps(conn).delete_conditions(
            "malformed.mdb", "1", ["7", "8"]
        )
        self.assertFalse(result)
        self.assertEqual(
            conn.execute("SELECT UID FROM BidConditions ORDER BY UID").fetchall(),
            [(7,), (8,)],
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidTakeoffs").fetchall(), [(70,)]
        )

    def test_bid_owned_bulk_deletes_reject_cross_bid_batches(self):
        fixtures = (
            (
                "condition folders",
                "CREATE TABLE BidConditionFolders ("
                "UID INTEGER, BidUID INTEGER, ParentUID INTEGER)",
                "BidConditionFolders",
            ),
            (
                "pages",
                "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
                "BidPages",
            ),
            (
                "takeoffs",
                "CREATE TABLE BidTakeoffs ("
                "UID INTEGER, BidUID INTEGER, ParentUID INTEGER)",
                "BidTakeoffs",
            ),
        )
        for operation, create_sql, table in fixtures:
            with self.subTest(operation=operation):
                conn = sqlite3.connect(":memory:")
                conn.execute(create_sql)
                if table in {"BidConditionFolders", "BidTakeoffs"}:
                    conn.executemany(
                        f"INSERT INTO [{table}] VALUES (?, ?, NULL)",
                        ((7, 1), (8, 2)),
                    )
                else:
                    conn.executemany(
                        f"INSERT INTO [{table}] VALUES (?, ?)", ((7, 1), (8, 2))
                    )
                operations = _SqliteDuplicateOps(conn)
                if table == "BidConditionFolders":
                    result = operations.delete_condition_folders(
                        "malformed.mdb", ["7", "8"]
                    )
                elif table == "BidPages":
                    result = operations.delete_pages("malformed.mdb", ["7", "8"])
                else:
                    result = operations.delete_takeoffs("malformed.mdb", ["7", "8"])
                self.assertFalse(result)
                self.assertEqual(
                    conn.execute(f"SELECT UID FROM [{table}] ORDER BY UID").fetchall(),
                    [(7,), (8,)],
                )

    def test_takeoff_bulk_saves_reject_cross_bid_batches_atomically(self):
        operations = (
            (
                "positions",
                lambda writer: writer.save_takeoff_positions(
                    "malformed.mdb", [(7, (10.0, 20.0)), (8, (30.0, 40.0))]
                ),
            ),
            (
                "rotations",
                lambda writer: writer.save_takeoff_rotations(
                    "malformed.mdb", [(7, 45.0), (8, 90.0)]
                ),
            ),
            (
                "text properties",
                lambda writer: writer.save_takeoff_text_properties(
                    "malformed.mdb",
                    [
                        (7, {"name_font_name": "First"}),
                        (8, {"name_font_name": "Second"}),
                    ],
                ),
            ),
        )
        for operation, mutate in operations:
            with self.subTest(operation=operation):
                conn = sqlite3.connect(":memory:")
                conn.execute(
                    "CREATE TABLE BidTakeoffs ("
                    "UID INTEGER, BidUID INTEGER, Position BLOB, "
                    "Rotation REAL, NameFontName TEXT)"
                )
                conn.executemany(
                    "INSERT INTO BidTakeoffs VALUES (?, ?, NULL, 0, 'Original')",
                    ((7, 1), (8, 2)),
                )
                self.assertFalse(mutate(_SqliteDuplicateOps(conn)))
                self.assertEqual(
                    conn.execute(
                        "SELECT UID, Position, Rotation, NameFontName "
                        "FROM BidTakeoffs ORDER BY UID"
                    ).fetchall(),
                    [(7, None, 0.0, "Original"), (8, None, 0.0, "Original")],
                )

    def test_root_hierarchy_inserts_require_authoritative_bid_before_allocation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT)"
        )
        conn.execute(
            "CREATE TABLE BidLayers ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, Sequence INTEGER)"
        )
        operations = _SqliteDuplicateOps(conn)
        self.assertIsNone(
            operations.insert_condition_folder(
                "malformed.mdb", "99", "Ownerless folder", None
            )
        )
        with self.assertRaises(RuntimeError):
            operations.insert_layer("malformed.mdb", "99", "Ownerless layer", 0)
        self.assertEqual(
            conn.execute("SELECT UID FROM BidConditionFolders").fetchall(), []
        )
        self.assertEqual(conn.execute("SELECT UID FROM BidLayers").fetchall(), [])

    def test_condition_cross_bid_duplicate_requires_destination_bid_before_insert(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER, BidUID INTEGER, GUID TEXT, RefNo INTEGER, Name TEXT, "
            "BidLayerUID INTEGER, BidConditionFolderUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "INSERT INTO BidConditions VALUES (7, 1, 'source-guid', 1, "
            "'Source', NULL, NULL)"
        )
        result = _SqliteDuplicateOps(conn).duplicate_conditions_to_bid(
            "malformed.mdb", "1", "99", ["7"]
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute("SELECT UID, BidUID FROM BidConditions").fetchall(),
            [(7, 1)],
        )

    def test_layer_insert_reserves_dangling_layer_reference_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidLayers ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, Show INTEGER, "
            "Sequence INTEGER, IsTemplate INTEGER, IsLocked INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidComments "
            "(UID INTEGER, BidUID INTEGER, BidLayerUID INTEGER)"
        )
        conn.execute("INSERT INTO BidLayers VALUES (7, 1, 'Existing', -1, 1, 0, 0)")
        conn.execute("INSERT INTO BidComments VALUES (70, 1, 8)")
        self.assertEqual(
            _SqliteDuplicateOps(conn).insert_layer("legacy.mdb", "1", "New", 1),
            "9",
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidLayers ORDER BY UID").fetchall(),
            [(7,), (9,)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM BidComments AS comment "
                "INNER JOIN BidLayers AS layer ON comment.BidLayerUID=layer.UID"
            ).fetchone()[0],
            0,
        )

    def test_page_folder_insert_reserves_dangling_parent_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        conn.execute(
            "CREATE TABLE BidPages "
            "(UID INTEGER, BidUID INTEGER, BidPageFolderUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidPageFolders "
            "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (1, 'Original')")
        conn.execute("INSERT INTO BidPageFolders VALUES (7, 1, 'Orphan', 8)")
        self.assertTrue(
            _SqliteDuplicateOps(conn).save_cover_sheet(
                "legacy.mdb",
                "1",
                {
                    "job_name": "Original",
                    "measure_base": 0,
                    "new_folders": [
                        {
                            "local_uid": "new_0",
                            "name": "Unrelated",
                            "parent_uid": None,
                        }
                    ],
                },
            )
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID FROM BidPageFolders ORDER BY UID"
            ).fetchall(),
            [(7, 8), (9, None)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM BidPageFolders AS child "
                "INNER JOIN BidPageFolders AS parent "
                "ON child.ParentUID=parent.UID"
            ).fetchone()[0],
            0,
        )

    def test_cover_sheet_rejects_folder_write_before_bid_update_when_table_missing(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        conn.execute("INSERT INTO Bids VALUES (1, 'Before')")
        self.assertFalse(
            _SqliteDuplicateOps(conn).save_cover_sheet(
                "legacy.mdb",
                "1",
                {
                    "job_name": "Changed",
                    "measure_base": 0,
                    "new_folders": [
                        {
                            "local_uid": "new_0",
                            "name": "Folder",
                            "parent_uid": None,
                        }
                    ],
                },
            )
        )
        self.assertEqual(
            conn.execute("SELECT JobName FROM Bids WHERE UID=1").fetchone()[0],
            "Before",
        )

    def test_cover_sheet_rejects_nested_folder_when_schema_is_flat(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        conn.execute("INSERT INTO Bids VALUES (1, 'Before')")
        conn.execute(
            "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT)"
        )
        self.assertFalse(
            _SqliteDuplicateOps(conn).save_cover_sheet(
                "legacy.mdb",
                "1",
                {
                    "job_name": "Changed",
                    "measure_base": 0,
                    "new_folders": [
                        {
                            "local_uid": "parent",
                            "name": "Parent",
                            "parent_uid": None,
                        },
                        {
                            "local_uid": "child",
                            "name": "Child",
                            "parent_uid": "parent",
                        },
                    ],
                },
            )
        )
        self.assertEqual(
            conn.execute("SELECT JobName FROM Bids WHERE UID=1").fetchone()[0],
            "Before",
        )
        self.assertEqual(conn.execute("SELECT UID FROM BidPageFolders").fetchall(), [])
        self.assertTrue(
            _SqliteDuplicateOps(conn).save_cover_sheet(
                "legacy.mdb",
                "1",
                {
                    "job_name": "Flat",
                    "measure_base": 0,
                    "new_folders": [
                        {
                            "local_uid": "root",
                            "name": "Root",
                            "parent_uid": None,
                        }
                    ],
                },
            )
        )
        self.assertEqual(
            conn.execute("SELECT BidUID, Name FROM BidPageFolders").fetchall(),
            [(1, "Root")],
        )

    def test_page_insert_reserves_dangling_ancillary_page_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT)")
        conn.execute("CREATE TABLE BidMarkedPages (UID INTEGER, BidPageUID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1, 'Bid')")
        conn.execute("INSERT INTO BidPages VALUES (7, 1, 'Existing')")
        conn.execute("INSERT INTO BidMarkedPages VALUES (1, 8)")
        success = _SqliteDuplicateOps(conn).save_cover_sheet(
            "legacy.mdb",
            "1",
            {
                "measure_base": 0,
                "pages": [
                    {
                        "uid": None,
                        "name": "New",
                        "width": 42.0,
                        "height": 30.0,
                        "scale_factor1": 0.125,
                        "scale_factor2": 12.0,
                        "show_mode": 0,
                    }
                ],
            },
        )
        self.assertTrue(success)
        self.assertEqual(
            conn.execute("SELECT UID FROM BidPages ORDER BY UID").fetchall(),
            [(7,), (9,)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM BidMarkedPages AS marked "
                "INNER JOIN BidPages AS page ON marked.BidPageUID=page.UID"
            ).fetchone()[0],
            0,
        )

    def test_cover_sheet_folder_save_rejects_cycle_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE Bids (UID INTEGER, JobName TEXT, MeasureBase INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidPages "
            "(UID INTEGER, BidUID INTEGER, BidPageFolderUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidPageFolders "
            "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (1, 'Original', 0)")
        conn.executemany(
            "INSERT INTO BidPageFolders VALUES (?, 1, ?, NULL)",
            ((7, "First"), (8, "Second")),
        )
        self.assertFalse(
            _SqliteDuplicateOps(conn).save_cover_sheet(
                "malformed.mdb",
                "1",
                {
                    "job_name": "Changed",
                    "measure_base": 0,
                    "folders": [
                        {"uid": "7", "name": "First", "parent_uid": "8"},
                        {"uid": "8", "name": "Second", "parent_uid": "7"},
                    ],
                },
            )
        )
        self.assertEqual(
            conn.execute("SELECT JobName FROM Bids WHERE UID=1").fetchone()[0],
            "Original",
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID FROM BidPageFolders ORDER BY UID"
            ).fetchall(),
            [(7, None), (8, None)],
        )

    def test_cover_sheet_new_folders_reject_pending_cycle_before_insert(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        conn.execute(
            "CREATE TABLE BidPages "
            "(UID INTEGER, BidUID INTEGER, BidPageFolderUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidPageFolders "
            "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (1, 'Original')")
        self.assertFalse(
            _SqliteDuplicateOps(conn).save_cover_sheet(
                "malformed.mdb",
                "1",
                {
                    "job_name": "Changed",
                    "measure_base": 0,
                    "new_folders": [
                        {"local_uid": "new_a", "name": "A", "parent_uid": "new_b"},
                        {"local_uid": "new_b", "name": "B", "parent_uid": "new_a"},
                    ],
                },
            )
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidPageFolders").fetchone()[0],
            0,
        )
        self.assertEqual(
            conn.execute("SELECT JobName FROM Bids WHERE UID=1").fetchone()[0],
            "Original",
        )

    def test_cover_sheet_folder_save_rejects_missing_or_cross_bid_parent(self):
        for parent_rows in ((), ((99, 2, "Other", None),)):
            with self.subTest(parent_rows=parent_rows):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
                conn.execute(
                    "CREATE TABLE BidPages "
                    "(UID INTEGER, BidUID INTEGER, BidPageFolderUID INTEGER)"
                )
                conn.execute(
                    "CREATE TABLE BidPageFolders "
                    "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
                )
                conn.execute("INSERT INTO Bids VALUES (1, 'Original')")
                conn.execute("INSERT INTO BidPageFolders VALUES (7, 1, 'Child', NULL)")
                conn.executemany(
                    "INSERT INTO BidPageFolders VALUES (?, ?, ?, ?)", parent_rows
                )
                self.assertFalse(
                    _SqliteDuplicateOps(conn).save_cover_sheet(
                        "malformed.mdb",
                        "1",
                        {
                            "job_name": "Changed",
                            "measure_base": 0,
                            "folders": [
                                {
                                    "uid": "7",
                                    "name": "Child",
                                    "parent_uid": "99",
                                }
                            ],
                        },
                    )
                )
                self.assertEqual(
                    conn.execute("SELECT JobName FROM Bids WHERE UID=1").fetchone()[0],
                    "Original",
                )

    def test_cover_sheet_folder_save_accepts_valid_multi_level_graph(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        conn.execute(
            "CREATE TABLE BidPages "
            "(UID INTEGER, BidUID INTEGER, BidPageFolderUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidPageFolders "
            "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (1, 'Original')")
        conn.executemany(
            "INSERT INTO BidPageFolders VALUES (?, 1, ?, ?)",
            ((7, "Root", None), (8, "Middle", 7), (9, "Leaf", 8)),
        )
        self.assertTrue(
            _SqliteDuplicateOps(conn).save_cover_sheet(
                "valid.mdb",
                "1",
                {
                    "job_name": "Changed",
                    "measure_base": 0,
                    "folders": [
                        {"uid": "7", "name": "Root", "parent_uid": None},
                        {"uid": "8", "name": "Middle", "parent_uid": "7"},
                        {"uid": "9", "name": "Leaf", "parent_uid": "8"},
                    ],
                },
            )
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID FROM BidPageFolders ORDER BY UID"
            ).fetchall(),
            [(7, None), (8, 7), (9, 8)],
        )

    def test_cover_sheet_page_move_rejects_cross_bid_folder_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        conn.execute(
            "CREATE TABLE BidPageFolders ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT)"
        )
        conn.execute(
            "CREATE TABLE BidPages ("
            "UID INTEGER, BidUID INTEGER, BidPageFolderUID INTEGER, Name TEXT, "
            "OverlayImagePath TEXT, ScaleFactor1 REAL, ScaleFactor2 REAL)"
        )
        conn.execute("INSERT INTO Bids VALUES (1, 'Original')")
        conn.execute("INSERT INTO Bids VALUES (2, 'Other')")
        conn.execute("INSERT INTO BidPageFolders VALUES (7, 2, NULL, 'Other')")
        conn.execute(
            "INSERT INTO BidPages VALUES (10, 1, NULL, 'Page', '', 0.125, 12.0)"
        )
        success = _SqliteDuplicateOps(conn).save_cover_sheet(
            "malformed.mdb",
            "1",
            {
                "measure_base": 0,
                "job_name": "Changed",
                "pages": [
                    {
                        "uid": "10",
                        "folder_uid": "7",
                        "name": "Page",
                        "width": 42.0,
                        "height": 30.0,
                        "scale_factor1": 0.125,
                        "scale_factor2": 12.0,
                        "show_mode": 0,
                    }
                ],
            },
        )
        self.assertFalse(success)
        self.assertEqual(
            conn.execute("SELECT JobName FROM Bids WHERE UID=1").fetchone()[0],
            "Original",
        )
        self.assertIsNone(
            conn.execute(
                "SELECT BidPageFolderUID FROM BidPages WHERE UID=10"
            ).fetchone()[0]
        )

    def test_cover_sheet_save_rejects_cross_bid_page_before_bid_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE Bids (UID INTEGER, JobName TEXT, MeasureBase INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidPages ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, OverlayImagePath TEXT, "
            "ScaleFactor1 REAL, ScaleFactor2 REAL)"
        )
        conn.executemany(
            "INSERT INTO Bids VALUES (?, ?, 0)",
            ((1, "Expected bid"), (2, "Other bid")),
        )
        conn.execute("INSERT INTO BidPages VALUES (20, 2, 'Other page', '', 1, 1)")
        success = _SqliteDuplicateOps(conn).save_cover_sheet(
            "malformed.mdb",
            "1",
            {
                "job_name": "Unexpected mutation",
                "measure_base": 0,
                "pages": [
                    {
                        "uid": "20",
                        "name": "Unexpected page mutation",
                        "width": 42.0,
                        "height": 30.0,
                        "scale_factor1": 1.0,
                        "scale_factor2": 1.0,
                        "show_mode": 0,
                    }
                ],
            },
        )
        self.assertFalse(success)
        self.assertEqual(
            conn.execute("SELECT JobName FROM Bids WHERE UID=1").fetchone()[0],
            "Expected bid",
        )
        self.assertEqual(
            conn.execute("SELECT Name FROM BidPages WHERE UID=20").fetchone()[0],
            "Other page",
        )

    def test_condition_insert_rejects_cross_bid_relationship_before_insert(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER, BidUID INTEGER, GUID TEXT, RefNo INTEGER, "
            "Name TEXT, Type INTEGER, BidLayerUID INTEGER, "
            "BidConditionFolderUID INTEGER)"
        )
        conn.execute("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidConditionFolders (UID INTEGER, BidUID INTEGER)")
        conn.executemany("INSERT INTO Bids VALUES (?)", ((1,), (2,)))
        conn.executemany("INSERT INTO BidLayers VALUES (?, ?)", ((7, 1), (8, 2)))
        conn.executemany(
            "INSERT INTO BidConditionFolders VALUES (?, ?)", ((9, 1), (10, 2))
        )
        result = _SqliteDuplicateOps(conn).insert_condition(
            "malformed.mdb",
            "1",
            CreateConditionSpec(
                name="Invalid",
                condition_type=1,
                layer_uid="8",
                folder_uid="9",
            ),
        )
        self.assertIsNone(result)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidConditions").fetchone()[0], 0
        )

    def test_condition_update_rejects_cross_bid_relationships_atomically(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, BidLayerUID INTEGER, "
            "BidConditionFolderUID INTEGER)"
        )
        conn.execute("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidConditionFolders (UID INTEGER, BidUID INTEGER)")
        conn.executemany("INSERT INTO Bids VALUES (?)", ((1,), (2,)))
        conn.execute("INSERT INTO BidConditions VALUES (50, 1, 'Original', 7, 9)")
        conn.executemany("INSERT INTO BidLayers VALUES (?, ?)", ((7, 1), (8, 2)))
        conn.executemany(
            "INSERT INTO BidConditionFolders VALUES (?, ?)", ((9, 1), (10, 2))
        )
        updates = UpdateConditionDto()
        updates.set("name", "Unexpected mutation")
        updates.set("layer_uid", "8")
        updates.set("folder_uid", "9")
        success = _SqliteDuplicateOps(conn).update_condition(
            "malformed.mdb", "1", "50", updates
        )
        self.assertFalse(success)
        self.assertEqual(
            conn.execute(
                "SELECT Name, BidLayerUID, BidConditionFolderUID "
                "FROM BidConditions WHERE UID=50"
            ).fetchone(),
            ("Original", 7, 9),
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

    def test_master_data_inserts_do_not_claim_dangling_reference_uids(self):
        employee = SimpleNamespace(
            uid="new_employee",
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
        fixtures = (
            (
                "JobStatuses",
                (
                    "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT)",
                    "CREATE TABLE Bids (UID INTEGER, JobStatusUID INTEGER)",
                ),
                (
                    "INSERT INTO JobStatuses VALUES (1, 'Existing')",
                    "INSERT INTO Bids VALUES (10, 2)",
                ),
                lambda ops: ops.save_job_statuses(
                    "legacy.mdb",
                    {"new": [{"uid": "new_status", "name": "New"}]},
                ),
                {"new_status": "3"},
            ),
            (
                "Employees",
                (
                    "CREATE TABLE Employees ("
                    "UID INTEGER, EmployeeNo TEXT, FirstName TEXT, LastName TEXT)",
                    "CREATE TABLE Bids (UID INTEGER, EstimatorUID INTEGER)",
                ),
                (
                    "INSERT INTO Employees VALUES (1, 'E1', 'Ava', 'Lee')",
                    "INSERT INTO Bids VALUES (10, 2)",
                ),
                lambda ops: ops.save_employees("legacy.mdb", {"new": [employee]}),
                {"new_employee": "3"},
            ),
            (
                "PayClasses",
                (
                    "CREATE TABLE PayClasses (UID INTEGER, Name TEXT)",
                    "CREATE TABLE Employees (UID INTEGER, PayClassUID INTEGER)",
                ),
                (
                    "INSERT INTO PayClasses VALUES (1, 'Existing')",
                    "INSERT INTO Employees VALUES (10, 2)",
                ),
                lambda ops: ops.save_pay_classes(
                    "legacy.mdb",
                    {"new": [{"uid": "new_class", "name": "New"}]},
                ),
                {"new_class": "3"},
            ),
            (
                "CdnTypes",
                (
                    "CREATE TABLE CdnTypes (UID INTEGER, Name TEXT)",
                    "CREATE TABLE BidConditions (UID INTEGER, CdnTypeUID INTEGER)",
                ),
                (
                    "INSERT INTO CdnTypes VALUES (1, 'Existing')",
                    "INSERT INTO BidConditions VALUES (10, 2)",
                ),
                lambda ops: ops.save_condition_types(
                    "legacy.mdb",
                    {"new": [{"uid": "new_type", "name": "New"}]},
                ),
                {"new_type": "3"},
            ),
        )
        for table, ddl, inserts, save, expected in fixtures:
            with self.subTest(table=table):
                conn = sqlite3.connect(":memory:")
                for statement in ddl:
                    conn.execute(statement)
                for statement in inserts:
                    conn.execute(statement)
                result = save(_SqliteDuplicateOps(conn))
                self.assertEqual(result, expected)
                self.assertEqual(
                    conn.execute(
                        f"SELECT [UID] FROM [{table}] ORDER BY [UID]"
                    ).fetchall(),
                    [(1,), (3,)],
                )

    def test_employee_batch_rejects_missing_pay_class_before_first_write(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE PayClasses (UID INTEGER, Name TEXT)")
        conn.execute("INSERT INTO PayClasses VALUES (1, 'Existing')")
        conn.execute(
            "CREATE TABLE Employees ("
            "UID INTEGER, EmployeeNo TEXT, FirstName TEXT, LastName TEXT, "
            "PayClassUID INTEGER)"
        )
        conn.execute("INSERT INTO Employees VALUES (7, 'E1', 'Before', 'User', 1)")

        def employee(uid, employee_no, first_name, pay_class_uid):
            return SimpleNamespace(
                uid=uid,
                employee_no=employee_no,
                first_name=first_name,
                last_name="User",
                address1="",
                address2="",
                city="",
                state="",
                zip="",
                home_phone="",
                mobile_phone="",
                email="",
                pay_class_uid=pay_class_uid,
            )

        with self.assertLogs("test", level="ERROR") as logs:
            result = _SqliteDuplicateOps(conn).save_employees(
                "malformed.mdb",
                {
                    "updated": [employee("7", "E1", "Changed", "1")],
                    "new": [employee("new_0", "E2", "New", "99")],
                },
            )
        self.assertIsNone(result)
        self.assertIn("PayClasses has no row for UID 99", logs.output[0])
        self.assertEqual(
            conn.execute(
                "SELECT UID, EmployeeNo, FirstName, PayClassUID "
                "FROM Employees ORDER BY UID"
            ).fetchall(),
            [(7, "E1", "Before", 1)],
        )

    def test_used_employee_uids_include_all_direct_bid_roles(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE Bids ("
            "UID INTEGER PRIMARY KEY, EstimatorUID INTEGER, "
            "PrManagerUID INTEGER, JobSiteManagerUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (1, 10, 20, 30)")
        used = SettingsReaderMixin._parse_used_employee_uids(
            _SqliteMdbOps(conn), _SqliteConnectionWrapper(conn)
        )
        self.assertEqual(used, {"10", "20", "30"})

    def test_condition_type_reader_rejects_duplicate_physical_uid(self):
        conn = sqlite3.connect(":memory:")
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

    def test_bid_dictionary_readers_reject_duplicate_authoritative_uids(self):
        fixtures = (
            (
                "BidLayers",
                "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT, Show INTEGER)",
                "INSERT INTO BidLayers VALUES (7, 1, ?, -1)",
                lambda ops, connection, schema: MdbReader._parse_bid_layers_for_bid(
                    ops, connection, "1"
                ),
            ),
            (
                "BidAreas",
                "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER, Name TEXT)",
                "INSERT INTO BidAreas (UID, BidUID, Name) VALUES (7, 1, ?)",
                lambda ops, connection, schema: MdbReader._parse_bid_areas_for_bid(
                    ops, connection, "1", schema
                ),
            ),
            (
                "BidConditionFolders",
                "CREATE TABLE BidConditionFolders (UID INTEGER, BidUID INTEGER, Name TEXT)",
                "INSERT INTO BidConditionFolders VALUES (7, 1, ?)",
                lambda ops, connection, schema: MdbReader._parse_bid_condition_folders_for_bid(
                    ops, connection, "1", schema
                ),
            ),
            (
                "BidPages",
                "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT)",
                "INSERT INTO BidPages (UID, BidUID, Name) VALUES (7, 1, ?)",
                lambda ops, connection, schema: MdbReader._parse_bid_pages_for_bid(
                    ops, connection, "1", {}, schema
                ),
            ),
            (
                "BidConditions",
                "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT, Type INTEGER)",
                "INSERT INTO BidConditions (UID, BidUID, Name, Type) VALUES (7, 1, ?, 1)",
                lambda ops, connection, schema: MdbReader._parse_bid_conditions_for_bid(
                    ops, connection, "1", {}, {}, schema
                ),
            ),
        )
        for table, ddl, insert_sql, load in fixtures:
            with self.subTest(table=table):
                conn = sqlite3.connect(":memory:")
                conn.execute(ddl)
                conn.executemany(insert_sql, (("First",), ("Conflicting",)))
                ops = _SqliteMdbOps(conn)
                connection = _SqliteConnectionWrapper(conn)
                with self.assertRaisesRegex(
                    RuntimeError,
                    f"{table} contains duplicate UID 7",
                ):
                    load(ops, connection, ops._schema_ref)

    def test_condition_folder_reader_rejects_parent_cycles(self):
        fixtures = (
            ((7, 7),),
            ((7, 8), (8, 7)),
            ((7, 8), (8, 9), (9, 7)),
        )
        for rows in fixtures:
            with self.subTest(rows=rows):
                conn = sqlite3.connect(":memory:")
                conn.execute(
                    "CREATE TABLE BidConditionFolders "
                    "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
                )
                conn.executemany(
                    "INSERT INTO BidConditionFolders VALUES (?, 1, 'Folder', ?)",
                    rows,
                )
                with self.assertRaisesRegex(
                    RuntimeError,
                    "BidConditionFolders.UID=7 participates in a ParentUID cycle",
                ):
                    MdbReader._parse_bid_condition_folders_for_bid(
                        _SqliteMdbOps(conn),
                        _SqliteConnectionWrapper(conn),
                        "1",
                        _SqliteSchema(conn),
                    )

    def test_bid_area_reader_rejects_missing_or_cross_bid_parent(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidAreas "
            "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidAreas VALUES (?, ?, ?, ?)",
            (
                (7, 1, "Missing parent", 99),
                (99, 2, "Other bid", None),
            ),
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "BidAreas.UID=7 references missing BidAreas.UID=99",
        ):
            MdbReader._parse_bid_areas_for_bid(
                _SqliteMdbOps(conn),
                _SqliteConnectionWrapper(conn),
                "1",
                _SqliteSchema(conn),
            )

    def test_bid_area_reader_rejects_parent_cycles(self):
        for rows in (
            ((7, 7),),
            ((7, 8), (8, 7)),
            ((7, 8), (8, 9), (9, 7)),
        ):
            with self.subTest(rows=rows):
                conn = sqlite3.connect(":memory:")
                conn.execute(
                    "CREATE TABLE BidAreas "
                    "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
                )
                conn.executemany("INSERT INTO BidAreas VALUES (?, 1, 'Area', ?)", rows)
                with self.assertRaisesRegex(
                    RuntimeError,
                    "BidAreas.UID=7 participates in a ParentUID cycle",
                ):
                    MdbReader._parse_bid_areas_for_bid(
                        _SqliteMdbOps(conn),
                        _SqliteConnectionWrapper(conn),
                        "1",
                        _SqliteSchema(conn),
                    )

    def test_bid_area_reader_accepts_valid_nested_hierarchy(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidAreas "
            "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidAreas VALUES (?, 1, ?, ?)",
            ((7, "Root", None), (8, "Middle", 7), (9, "Leaf", 8)),
        )
        areas = MdbReader._parse_bid_areas_for_bid(
            _SqliteMdbOps(conn),
            _SqliteConnectionWrapper(conn),
            "1",
            _SqliteSchema(conn),
        )
        self.assertEqual(list(areas), ["7", "8", "9"])

    def test_bid_area_reader_normalizes_zero_parent_to_root(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidAreas "
            "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        conn.execute("INSERT INTO BidAreas VALUES (7, 1, 'Root', 0)")
        areas = MdbReader._parse_bid_areas_for_bid(
            _SqliteMdbOps(conn),
            _SqliteConnectionWrapper(conn),
            "1",
            _SqliteSchema(conn),
        )
        self.assertEqual(areas["7"].parent_uid, "")

    def test_condition_folder_reader_preserves_orphan_and_valid_chain_contracts(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidConditionFolders "
            "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidConditionFolders VALUES (?, ?, ?, ?)",
            (
                (7, 1, "Root", None),
                (8, 1, "Middle", 7),
                (9, 1, "Leaf", 8),
                (10, 1, "Missing parent", 99),
                (99, 2, "Other bid", None),
                (11, 1, "Cross-bid parent", 99),
            ),
        )
        folders = MdbReader._parse_bid_condition_folders_for_bid(
            _SqliteMdbOps(conn),
            _SqliteConnectionWrapper(conn),
            "1",
            _SqliteSchema(conn),
        )
        self.assertEqual(folders["8"].parent_uid, "7")
        self.assertEqual(folders["9"].parent_uid, "8")
        self.assertEqual(folders["10"].parent_uid, "99")
        self.assertEqual(folders["11"].parent_uid, "99")

    def test_bid_layer_reader_rejects_null_zero_and_whitespace_uids(self):
        for malformed_uid in (None, 0, "0", "   "):
            with self.subTest(uid=malformed_uid):
                conn = sqlite3.connect(":memory:")
                conn.execute(
                    "CREATE TABLE BidLayers (UID, BidUID INTEGER, Name TEXT, Show INTEGER)"
                )
                conn.execute(
                    "INSERT INTO BidLayers VALUES (?, 1, 'Malformed', -1)",
                    (malformed_uid,),
                )
                with self.assertRaisesRegex(
                    RuntimeError,
                    "BidLayers contains malformed UID",
                ):
                    MdbReader._parse_bid_layers_for_bid(
                        _SqliteMdbOps(conn), _SqliteConnectionWrapper(conn), "1"
                    )

    def test_project_rename_rejects_duplicate_physical_uid_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidProjects (UID INTEGER, Name TEXT)")
        conn.executemany(
            "INSERT INTO BidProjects VALUES (7, ?)",
            (("First",), ("Conflicting",)),
        )
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).rename_project(
                    "malformed.mdb", "7", "Unexpected mutation"
                )
            )
        self.assertIn("BidProjects contains duplicate UID 7", logs.output[0])
        self.assertEqual(
            conn.execute("SELECT Name FROM BidProjects ORDER BY rowid").fetchall(),
            [("First",), ("Conflicting",)],
        )

    def test_move_bid_rejects_missing_project_owner_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidProjects (UID INTEGER, Name TEXT)")
        conn.execute(
            "CREATE TABLE Bids (UID INTEGER, BidProjectUID INTEGER, OrigBidProjectUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (11, NULL, NULL)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).move_bids_to_project("malformed.mdb", ["11"], "99")
            )
        self.assertIn("BidProjects has no row for UID 99", logs.output[0])
        self.assertIsNone(
            conn.execute("SELECT BidProjectUID FROM Bids WHERE UID=11").fetchone()[0]
        )

    def test_move_bid_rejects_missing_restore_project_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidProjects (UID INTEGER, Name TEXT)")
        conn.execute(
            "CREATE TABLE Bids ("
            "UID INTEGER, BidProjectUID INTEGER, OrigBidProjectUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidProjects VALUES (?, ?)", ((1, "Deleted"), (2, "Active"))
        )
        conn.execute("INSERT INTO Bids VALUES (11, 2, NULL)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).move_bids_to_project(
                    "malformed.mdb", ["11"], "1", "99"
                )
            )
        self.assertIn("BidProjects has no row for UID 99", logs.output[0])
        self.assertEqual(
            conn.execute(
                "SELECT BidProjectUID, OrigBidProjectUID FROM Bids WHERE UID=11"
            ).fetchone(),
            (2, None),
        )

    def test_move_bids_rejects_missing_batch_member_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidProjects (UID INTEGER, Name TEXT)")
        conn.execute(
            "CREATE TABLE Bids (UID INTEGER, BidProjectUID INTEGER, OrigBidProjectUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidProjects VALUES (?, ?)", ((1, "Source"), (2, "Target"))
        )
        conn.execute("INSERT INTO Bids VALUES (11, 1, NULL)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).move_bids_to_project(
                    "malformed.mdb", ["11", "99"], "2"
                )
            )
        self.assertIn("Bids has no row for UID 99", logs.output[0])
        self.assertEqual(
            conn.execute("SELECT BidProjectUID FROM Bids WHERE UID=11").fetchone()[0],
            1,
        )

    def test_create_bid_rejects_missing_project_owner_before_allocation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (12)")
        conn.execute("CREATE TABLE BidProjects (UID INTEGER, Name TEXT)")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertIsNone(
                _SqliteMdbOps(conn).create_bid(
                    "malformed.mdb", "99", {"job_name": "No owner"}
                )
            )
        self.assertIn("BidProjects has no row for UID 99", logs.output[0])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 0)

    def test_create_bid_rejects_folder_references_outside_new_bid_before_insert(self):
        invalid_updates = (
            {
                "job_name": "Cross-bid folder parent",
                "new_folders": [
                    {"local_uid": "new-folder", "name": "Child", "parent_uid": "7"}
                ],
            },
            {
                "job_name": "Cross-bid page folder",
                "pages": [
                    {
                        "name": "Page",
                        "width": 42.0,
                        "height": 30.0,
                        "folder_uid": "7",
                    }
                ],
            },
        )
        for updates in invalid_updates:
            with self.subTest(job_name=updates["job_name"]):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
                conn.execute("INSERT INTO Settings VALUES (2)")
                conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
                conn.execute("INSERT INTO Bids VALUES (1, 'Existing')")
                conn.execute(
                    "CREATE TABLE BidPageFolders ("
                    "UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
                )
                conn.execute(
                    "INSERT INTO BidPageFolders VALUES (7, 1, 'Existing', NULL)"
                )
                conn.execute(
                    "CREATE TABLE BidPages ("
                    "UID INTEGER, BidUID INTEGER, Name TEXT, Width REAL, "
                    "Height REAL, BidPageFolderUID INTEGER)"
                )
                self.assertIsNone(
                    _SqliteDuplicateOps(conn).create_bid("malformed.mdb", None, updates)
                )
                self.assertEqual(
                    conn.execute("SELECT UID FROM Bids ORDER BY UID").fetchall(),
                    [(1,)],
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT UID FROM BidPageFolders ORDER BY UID"
                    ).fetchall(),
                    [(7,)],
                )
                self.assertEqual(
                    conn.execute("SELECT UID FROM BidPages").fetchall(), []
                )

    def test_create_bid_rejects_missing_optional_master_references_before_allocation(
        self,
    ):
        for field, value in (("job_status_uid", "8"), ("estimator_uid", "9")):
            with self.subTest(field=field):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
                conn.execute("INSERT INTO Settings VALUES (12)")
                conn.execute(
                    "CREATE TABLE Bids ("
                    "UID INTEGER, JobName TEXT, JobStatusUID INTEGER, EstimatorUID INTEGER)"
                )
                conn.execute("CREATE TABLE JobStatuses (UID INTEGER)")
                conn.execute("CREATE TABLE Employees (UID INTEGER)")
                conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
                updates = {"job_name": "Invalid master", field: value}
                if field == "estimator_uid":
                    conn.execute("INSERT INTO JobStatuses VALUES (8)")
                    updates["job_status_uid"] = "8"
                with self.assertLogs("test", level="ERROR") as logs:
                    self.assertIsNone(
                        _SqliteDuplicateOps(conn).create_bid(
                            "malformed.mdb", None, updates
                        )
                    )
                expected_table = (
                    "JobStatuses" if field == "job_status_uid" else "Employees"
                )
                self.assertIn(
                    f"{expected_table} has no row for UID {value}", logs.output[0]
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 0
                )
                self.assertEqual(
                    conn.execute("SELECT NextBidNo FROM Settings").fetchone()[0], 12
                )

    def test_cover_sheet_rejects_missing_optional_master_reference_before_bid_update(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE Bids ("
            "UID INTEGER, JobName TEXT, JobStatusUID INTEGER, EstimatorUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (7, 'Before', 8, NULL)")
        conn.execute("CREATE TABLE JobStatuses (UID INTEGER)")
        conn.execute("INSERT INTO JobStatuses VALUES (8)")
        conn.execute("CREATE TABLE Employees (UID INTEGER)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteDuplicateOps(conn).save_cover_sheet(
                    "malformed.mdb",
                    "7",
                    {
                        "job_name": "After",
                        "job_status_uid": "8",
                        "estimator_uid": "9",
                        "measure_base": 0,
                    },
                )
            )
        self.assertIn("Employees has no row for UID 9", logs.output[0])
        self.assertEqual(
            conn.execute(
                "SELECT JobName, JobStatusUID, EstimatorUID FROM Bids WHERE UID=7"
            ).fetchone(),
            ("Before", 8, None),
        )

    def test_bid_status_update_rejects_missing_master_reference(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobStatusUID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (7, NULL)")
        conn.execute("CREATE TABLE JobStatuses (UID INTEGER)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteDuplicateOps(conn).update_bid_job_status(
                    "malformed.mdb", "7", "9"
                )
            )
        self.assertIn("JobStatuses has no row for UID 9", logs.output[0])
        self.assertIsNone(
            conn.execute("SELECT JobStatusUID FROM Bids WHERE UID=7").fetchone()[0]
        )

    def test_create_bid_accepts_forward_new_folder_reference_after_drag_reorder(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (2)")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        conn.execute(
            "CREATE TABLE BidPageFolders ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        result = _SqliteDuplicateOps(conn).create_bid(
            "new.mdb",
            None,
            {
                "job_name": "Forward folders",
                "new_folders": [
                    {
                        "local_uid": "child",
                        "name": "Child",
                        "parent_uid": "parent",
                    },
                    {
                        "local_uid": "parent",
                        "name": "Parent",
                        "parent_uid": None,
                    },
                ],
            },
        )
        self.assertEqual(result, "1")
        rows = conn.execute(
            "SELECT child.Name, parent.Name "
            "FROM BidPageFolders AS child "
            "JOIN BidPageFolders AS parent ON parent.UID=child.ParentUID"
        ).fetchall()
        self.assertEqual(rows, [("Child", "Parent")])

    def test_create_bid_rejects_nested_folders_when_schema_is_flat(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (2)")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        conn.execute(
            "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT)"
        )
        result = _SqliteDuplicateOps(conn).create_bid(
            "legacy.mdb",
            None,
            {
                "job_name": "Nested folders",
                "new_folders": [
                    {
                        "local_uid": "parent",
                        "name": "Parent",
                        "parent_uid": None,
                    },
                    {
                        "local_uid": "child",
                        "name": "Child",
                        "parent_uid": "parent",
                    },
                ],
            },
        )
        self.assertIsNone(result)
        self.assertEqual(conn.execute("SELECT UID FROM Bids").fetchall(), [])
        self.assertEqual(conn.execute("SELECT UID FROM BidPageFolders").fetchall(), [])
        self.assertEqual(
            _SqliteDuplicateOps(conn).create_bid(
                "legacy.mdb",
                None,
                {
                    "job_name": "Flat folders",
                    "new_folders": [
                        {
                            "local_uid": "root",
                            "name": "Root",
                            "parent_uid": None,
                        }
                    ],
                },
            ),
            "1",
        )
        self.assertEqual(
            conn.execute("SELECT BidUID, Name FROM BidPageFolders").fetchall(),
            [(1, "Root")],
        )

    def test_create_bid_rejects_folders_when_legacy_table_is_unavailable(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (2)")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        result = _SqliteDuplicateOps(conn).create_bid(
            "legacy.mdb",
            None,
            {
                "job_name": "Folder bid",
                "new_folders": [
                    {
                        "local_uid": "folder",
                        "name": "Folder",
                        "parent_uid": None,
                    }
                ],
            },
        )
        self.assertIsNone(result)
        self.assertEqual(conn.execute("SELECT UID FROM Bids").fetchall(), [])

    def test_duplicate_bid_rejects_dangling_optional_master_references(self):
        for column, value, expected_table in (
            ("JobStatusUID", 8, "JobStatuses"),
            ("EstimatorUID", 9, "Employees"),
            ("PrManagerUID", 10, "Employees"),
            ("JobSiteManagerUID", 11, "Employees"),
        ):
            with self.subTest(column=column):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
                conn.execute("INSERT INTO Settings VALUES (12)")
                conn.execute(
                    "CREATE TABLE Bids ("
                    "UID INTEGER, BidNo INTEGER, GUID TEXT, "
                    "JobStatusUID INTEGER, EstimatorUID INTEGER, "
                    "PrManagerUID INTEGER, JobSiteManagerUID INTEGER)"
                )
                values = {
                    "JobStatusUID": None,
                    "EstimatorUID": None,
                    "PrManagerUID": None,
                    "JobSiteManagerUID": None,
                }
                values[column] = value
                conn.execute(
                    "INSERT INTO Bids VALUES (7, 11, 'source', ?, ?, ?, ?)",
                    (
                        values["JobStatusUID"],
                        values["EstimatorUID"],
                        values["PrManagerUID"],
                        values["JobSiteManagerUID"],
                    ),
                )
                conn.execute("CREATE TABLE JobStatuses (UID INTEGER)")
                conn.execute("CREATE TABLE Employees (UID INTEGER)")
                conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
                with self.assertLogs("test", level="ERROR") as logs:
                    self.assertIsNone(
                        _SqliteDuplicateOps(conn).duplicate_bid("malformed.mdb", "7")
                    )
                self.assertIn(
                    f"{expected_table} has no row for UID {value}", logs.output[0]
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 1
                )
                self.assertEqual(
                    conn.execute("SELECT NextBidNo FROM Settings").fetchone()[0], 12
                )

    def test_bid_delete_rejects_duplicate_physical_uid_before_cascade(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.executemany("INSERT INTO Bids VALUES (7)", ((), ()))
        conn.execute("INSERT INTO BidPages VALUES (70, 7)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(_SqliteMdbOps(conn).delete_bids("malformed.mdb", ["7"]))
        self.assertIn("Bids contains duplicate UID 7", logs.output[0])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidPages").fetchone()[0], 1)

    def test_bid_status_update_rejects_duplicate_physical_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobStatusUID INTEGER)")
        conn.executemany("INSERT INTO Bids VALUES (7, ?)", ((10,), (20,)))
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).update_bid_job_status("malformed.mdb", "7", "30")
            )
        self.assertIn("Bids contains duplicate UID 7", logs.output[0])
        self.assertEqual(
            conn.execute("SELECT JobStatusUID FROM Bids ORDER BY rowid").fetchall(),
            [(10,), (20,)],
        )

    def test_duplicate_bid_rejects_duplicate_source_uid_before_allocation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        conn.executemany(
            "INSERT INTO Bids VALUES (7, ?)",
            (("First",), ("Conflicting",)),
        )
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertIsNone(_SqliteMdbOps(conn).duplicate_bid("malformed.mdb", "7"))
        self.assertIn("Bids contains duplicate UID 7", logs.output[0])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 2)

    def test_duplicate_bid_rejects_dangling_hotlink_before_uid_collision_retargets_it(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (2)")
        conn.execute("CREATE TABLE Bids (UID INTEGER, BidNo INTEGER, JobName TEXT)")
        conn.execute("INSERT INTO Bids VALUES (1, 1, 'Source')")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidPages VALUES (20, 1)")
        conn.execute(
            "CREATE TABLE BidNamedViews "
            "(UID INTEGER, BidUID INTEGER, BidPageUID INTEGER)"
        )
        conn.execute("INSERT INTO BidNamedViews VALUES (5, 1, 20)")
        conn.execute(
            "CREATE TABLE BidHotLinks "
            "(UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, BidPageViewUID INTEGER)"
        )
        conn.execute("INSERT INTO BidHotLinks VALUES (40, 1, 20, 6)")
        with self.assertLogs("test", level="ERROR") as logs:
            duplicate_uid = _SqliteDuplicateOps(conn).duplicate_bid(
                "malformed.mdb", "1"
            )
        self.assertIsNone(duplicate_uid)
        self.assertIn(
            "BidHotLinks.UID=40 references missing BidNamedViews.UID=6",
            logs.output[0],
        )
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 1)

    def test_duplicate_bid_does_not_claim_orphan_bid_owned_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (2)")
        conn.execute("CREATE TABLE Bids (UID INTEGER, BidNo INTEGER, JobName TEXT)")
        conn.execute("INSERT INTO Bids VALUES (1, 1, 'Source')")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidNotes (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidNotes VALUES (10, 2)")
        duplicate_uid = _SqliteDuplicateOps(conn).duplicate_bid("legacy.mdb", "1")
        self.assertEqual(duplicate_uid, "3")
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM BidNotes AS note "
                "INNER JOIN Bids AS bid ON note.BidUID=bid.UID"
            ).fetchone()[0],
            0,
        )

    def test_duplicate_bid_page_does_not_claim_orphan_page_companion(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Settings (NextBidNo INTEGER)")
        conn.execute("INSERT INTO Settings VALUES (2)")
        conn.execute("CREATE TABLE Bids (UID INTEGER, BidNo INTEGER, JobName TEXT)")
        conn.execute("INSERT INTO Bids VALUES (1, 1, 'Source')")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidPages VALUES (20, 1)")
        conn.execute("CREATE TABLE BidMarkedPages (UID INTEGER, BidPageUID INTEGER)")
        conn.execute("INSERT INTO BidMarkedPages VALUES (1, 21)")
        duplicate_uid = _SqliteDuplicateOps(conn).duplicate_bid("legacy.mdb", "1")
        self.assertEqual(duplicate_uid, "2")
        self.assertEqual(
            conn.execute("SELECT UID FROM BidPages WHERE BidUID=2").fetchone()[0],
            22,
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM BidMarkedPages AS marked "
                "INNER JOIN BidPages AS page ON marked.BidPageUID=page.UID "
                "WHERE marked.UID=1"
            ).fetchone()[0],
            0,
        )

    def test_duplicate_bid_relationship_preflight_rejects_cross_bid_target(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidNamedViews "
            "(UID INTEGER, BidUID INTEGER, BidPageUID INTEGER)"
        )
        conn.execute("INSERT INTO BidNamedViews VALUES (5, 2, 20)")
        conn.execute(
            "CREATE TABLE BidHotLinks "
            "(UID INTEGER, BidUID INTEGER, BidPageViewUID INTEGER)"
        )
        conn.execute("INSERT INTO BidHotLinks VALUES (40, 1, 5)")
        ops = _SqliteDuplicateOps(conn)
        with self.assertRaisesRegex(
            RuntimeError,
            "BidHotLinks.UID=40 references missing BidNamedViews.UID=5",
        ):
            ops._require_duplicable_bid_relationships(
                _SqliteCursorWrapper(conn), ops._schema_ref, 1
            )

    def test_duplicate_bid_relationship_preflight_rejects_cross_bid_layer(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidLayers VALUES (5, 2)")
        conn.execute(
            "CREATE TABLE BidConditions "
            "(UID INTEGER, BidUID INTEGER, BidLayerUID INTEGER)"
        )
        conn.execute("INSERT INTO BidConditions VALUES (40, 1, 5)")
        ops = _SqliteDuplicateOps(conn)
        with self.assertRaisesRegex(
            RuntimeError,
            "BidConditions.UID=40 references missing BidLayers.UID=5",
        ):
            ops._require_duplicable_bid_relationships(
                _SqliteCursorWrapper(conn), ops._schema_ref, 1
            )

    def test_duplicate_bid_relationship_preflight_accepts_null_optional_layer(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditions "
            "(UID INTEGER, BidUID INTEGER, BidLayerUID INTEGER)"
        )
        conn.execute("INSERT INTO BidConditions VALUES (40, 1, NULL)")
        ops = _SqliteDuplicateOps(conn)
        ops._require_duplicable_bid_relationships(
            _SqliteCursorWrapper(conn), ops._schema_ref, 1
        )

    def test_duplicate_bid_relationship_preflight_rejects_takeoff_parent_cycle(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidTakeoffs "
            "(UID INTEGER, BidUID INTEGER, ParentUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidTakeoffs VALUES (?, 1, ?)",
            ((7, 8), (8, 7)),
        )
        ops = _SqliteDuplicateOps(conn)
        with self.assertRaisesRegex(
            RuntimeError,
            "BidTakeoffs.UID=7 participates in a ParentUID cycle",
        ):
            ops._require_duplicable_bid_relationships(
                _SqliteCursorWrapper(conn), ops._schema_ref, 1
            )

    def test_duplicate_bid_relationship_preflight_accepts_valid_parent_chain(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidTakeoffs "
            "(UID INTEGER, BidUID INTEGER, ParentUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidTakeoffs VALUES (?, 1, ?)",
            ((7, None), (8, 7), (9, 8)),
        )
        ops = _SqliteDuplicateOps(conn)
        ops._require_duplicable_bid_relationships(
            _SqliteCursorWrapper(conn), ops._schema_ref, 1
        )

    def test_duplicate_bid_relationship_preflight_accepts_valid_area_chain(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidAreas " "(UID INTEGER, BidUID INTEGER, ParentUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidAreas VALUES (?, 1, ?)",
            ((7, None), (8, 7), (9, 8)),
        )
        ops = _SqliteDuplicateOps(conn)
        ops._require_duplicable_bid_relationships(
            _SqliteCursorWrapper(conn), ops._schema_ref, 1
        )

    def test_duplicate_bid_relationship_preflight_rejects_hierarchy_parent_cycles(self):
        for table in ("BidAreas", "BidConditionFolders", "BidPageFolders"):
            with self.subTest(table=table):
                conn = sqlite3.connect(":memory:")
                conn.execute(
                    f"CREATE TABLE {table} "
                    "(UID INTEGER, BidUID INTEGER, ParentUID INTEGER)"
                )
                conn.executemany(
                    f"INSERT INTO {table} VALUES (?, 1, ?)",
                    ((7, 8), (8, 7)),
                )
                ops = _SqliteDuplicateOps(conn)
                with self.assertRaisesRegex(
                    RuntimeError,
                    rf"{table}.UID=7 participates in a ParentUID cycle",
                ):
                    ops._require_duplicable_bid_relationships(
                        _SqliteCursorWrapper(conn), ops._schema_ref, 1
                    )

    def test_duplicate_bid_preflight_rejects_indirect_area_count_target(self):
        for typical_area_rows in ((), ((21, 2),)):
            with self.subTest(typical_area_rows=typical_area_rows):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)")
                conn.execute("CREATE TABLE BidTypAreas (UID INTEGER, BidUID INTEGER)")
                conn.execute(
                    "CREATE TABLE BidTypAreaCounts ("
                    "UID INTEGER, BidAreaUID INTEGER, BidTypAreaUID INTEGER)"
                )
                conn.execute("INSERT INTO BidAreas VALUES (10, 1)")
                conn.execute("INSERT INTO BidTypAreas VALUES (20, 1)")
                conn.executemany(
                    "INSERT INTO BidTypAreas VALUES (?, ?)", typical_area_rows
                )
                conn.execute("INSERT INTO BidTypAreaCounts VALUES (30, 10, 21)")
                ops = _SqliteDuplicateOps(conn)
                with self.assertRaisesRegex(
                    RuntimeError,
                    "BidTypAreaCounts.UID=30 references missing " "BidTypAreas.UID=21",
                ):
                    ops._require_duplicable_bid_relationships(
                        _SqliteCursorWrapper(conn), ops._schema_ref, 1
                    )

    def test_duplicate_bid_preflight_rejects_indirect_page_child_target(self):
        for area_rows in ((), ((21, 2),)):
            with self.subTest(area_rows=area_rows):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
                conn.execute("CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)")
                conn.execute(
                    "CREATE TABLE BidPageSettings ("
                    "UID INTEGER, BidPageUID INTEGER, BidAreaUID INTEGER)"
                )
                conn.execute("INSERT INTO BidPages VALUES (10, 1)")
                conn.execute("INSERT INTO BidAreas VALUES (20, 1)")
                conn.executemany("INSERT INTO BidAreas VALUES (?, ?)", area_rows)
                conn.execute("INSERT INTO BidPageSettings VALUES (30, 10, 21)")
                ops = _SqliteDuplicateOps(conn)
                with self.assertRaisesRegex(
                    RuntimeError,
                    "BidPageSettings.UID=30 references missing BidAreas.UID=21",
                ):
                    ops._require_duplicable_bid_relationships(
                        _SqliteCursorWrapper(conn), ops._schema_ref, 1
                    )

    def test_takeoff_update_rejects_duplicate_physical_uid_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, IsNegativeQuantity INTEGER)"
        )
        conn.executemany("INSERT INTO BidTakeoffs VALUES (7, ?, ?)", ((1, 0), (2, -1)))
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).set_takeoffs_negative("malformed.mdb", ["7"], True)
            )
        self.assertIn("BidTakeoffs contains duplicate UID 7", logs.output[0])
        self.assertEqual(
            conn.execute(
                "SELECT BidUID, IsNegativeQuantity FROM BidTakeoffs ORDER BY rowid"
            ).fetchall(),
            [(1, 0), (2, -1)],
        )

    def test_takeoff_delete_rejects_duplicate_physical_uid_before_cascade(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, ParentUID INTEGER)"
        )
        conn.executemany("INSERT INTO BidTakeoffs VALUES (7, 1, NULL)", ((), ()))
        conn.execute("INSERT INTO BidTakeoffs VALUES (8, 1, 7)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).delete_takeoffs("malformed.mdb", ["7"])
            )
        self.assertIn("BidTakeoffs contains duplicate UID 7", logs.output[0])
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID FROM BidTakeoffs ORDER BY rowid"
            ).fetchall(),
            [(7, None), (7, None), (8, 7)],
        )

    def test_takeoff_delete_clears_all_surviving_self_references(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, "
            "TypGroupTakeoffUID INTEGER, "
            "TypPageTakeoffUID INTEGER, TypGroupMarkerUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidTakeoffs VALUES (?, 1, ?, ?, ?, ?)",
            ((7, None, None, None, None), (8, 7, 7, 7, 7)),
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_takeoffs("bid.mdb", ["7"]))
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID, TypGroupTakeoffUID, TypPageTakeoffUID, "
                "TypGroupMarkerUID FROM BidTakeoffs"
            ).fetchall(),
            [(8, None, None, None, None)],
        )

    def test_layer_update_rejects_duplicate_physical_uid_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Show INTEGER)"
        )
        conn.executemany("INSERT INTO BidLayers VALUES (7, ?, ?)", ((1, 0), (2, -1)))
        with self.assertRaisesRegex(
            RuntimeError,
            "BidLayers contains duplicate UID 7",
        ):
            _SqliteMdbOps(conn).update_layer_show("malformed.mdb", "7", True)
        self.assertEqual(
            conn.execute(
                "SELECT BidUID, Show FROM BidLayers ORDER BY rowid"
            ).fetchall(),
            [(1, 0), (2, -1)],
        )

    def test_page_delete_rejects_duplicate_physical_uid_before_cascade(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidTakeoffs (UID INTEGER, BidPageUID INTEGER)")
        conn.executemany("INSERT INTO BidPages VALUES (7, ?)", ((1,), (2,)))
        conn.execute("INSERT INTO BidTakeoffs VALUES (70, 7)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(_SqliteMdbOps(conn).delete_pages("malformed.mdb", ["7"]))
        self.assertIn("BidPages contains duplicate UID 7", logs.output[0])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidPages").fetchone()[0], 2)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidTakeoffs").fetchone()[0], 1
        )

    def test_condition_delete_rejects_duplicate_physical_uid_before_cascade(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER)"
        )
        conn.executemany("INSERT INTO BidConditions VALUES (?, ?)", ((7, 1), (7, 1)))
        conn.execute("INSERT INTO BidTakeoffs VALUES (70, 1, 7)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).delete_conditions("malformed.mdb", "1", ["7"])
            )
        self.assertIn("BidConditions contains duplicate UID 7", logs.output[0])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidConditions").fetchone()[0], 2
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidTakeoffs").fetchone()[0], 1
        )

    def test_area_delete_rejects_duplicate_physical_uid_before_cascade(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidTakeoffs (UID INTEGER, BidAreaUID INTEGER)")
        conn.executemany("INSERT INTO BidAreas VALUES (?, ?)", ((7, 1), (7, 1)))
        conn.execute("INSERT INTO BidTakeoffs VALUES (70, 7)")
        with self.assertLogs("test", level="ERROR") as logs:
            result = _SqliteMdbOps(conn).save_bid_areas(
                "malformed.mdb",
                "1",
                BidAreaChangeset(new=[], updated=[], deleted_uids=["7"]),
            )
        self.assertEqual(result, {})
        self.assertIn("BidAreas contains duplicate UID 7", logs.output[0])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidAreas").fetchone()[0], 2)
        self.assertEqual(
            conn.execute("SELECT BidAreaUID FROM BidTakeoffs").fetchall(), [(7,)]
        )

    def test_duplicate_row_copy_rejects_duplicate_source_uid_before_inserting(self):
        class DuplicateOps(_SqliteMdbOps):
            @staticmethod
            def _execute_insert_values(
                cursor,
                _schema,
                table,
                values,
                _required_columns,
                _operation,
            ):
                columns = list(values)
                cursor.execute(
                    f"INSERT INTO [{table}] "
                    f"({', '.join(f'[{column}]' for column in columns)}) "
                    f"VALUES ({', '.join('?' for _column in columns)})",
                    *[values[column] for column in columns],
                )

        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT)")
        conn.executemany(
            "INSERT INTO BidLayers VALUES (7, 1, ?)",
            (("First",), ("Conflicting",)),
        )
        ops = DuplicateOps(conn)
        with self.assertRaisesRegex(
            RuntimeError,
            "BidLayers contains duplicate UID 7",
        ):
            ops._copy_bid_table_rows(
                _SqliteCursorWrapper(conn), "BidLayers", "BidUID", "1", "2"
            )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidLayers").fetchone()[0], 2
        )

    def test_duplicate_uid_map_copy_rejects_duplicate_source_uid_before_inserting(self):
        class DuplicateOps(_SqliteMdbOps):
            @staticmethod
            def _execute_insert_values(
                cursor,
                _schema,
                table,
                values,
                _required_columns,
                _operation,
            ):
                columns = list(values)
                cursor.execute(
                    f"INSERT INTO [{table}] "
                    f"({', '.join(f'[{column}]' for column in columns)}) "
                    f"VALUES ({', '.join('?' for _column in columns)})",
                    *[values[column] for column in columns],
                )

        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT)")
        conn.executemany(
            "INSERT INTO BidLayers VALUES (7, 1, ?)",
            (("First",), ("Conflicting",)),
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "BidLayers contains duplicate UID 7",
        ):
            DuplicateOps(conn)._copy_with_uid_map(
                _SqliteCursorWrapper(conn), "BidLayers", "BidUID", "1", "2"
            )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidLayers").fetchone()[0], 2
        )

    def test_hierarchy_reader_rejects_duplicate_job_status_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE JobStatuses (UID INTEGER, Name TEXT)")
        conn.executemany(
            "INSERT INTO JobStatuses VALUES (7, ?)",
            (("Open",), ("Conflicting",)),
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "JobStatuses contains duplicate UID 7",
        ):
            MdbReader._load_status_map(
                _SqliteMdbOps(conn), _SqliteConnectionWrapper(conn)
            )

    def test_cover_sheet_reader_rejects_duplicate_employee_and_pay_class_uids(self):
        class Reader(SettingsReaderMixin, _SqliteMdbOps):
            def _select_all_unfiltered(self, connection, table):
                return MdbReader._select_all_unfiltered(self, connection, table)

            def _select_all_columns(self, schema, table):
                return MdbReader._select_all_columns(self, schema, table)

        fixtures = (
            (
                "Employees",
                "CREATE TABLE Employees (UID INTEGER, FirstName TEXT)",
                "CREATE TABLE PayClasses (UID INTEGER, Name TEXT)",
                "INSERT INTO Employees VALUES (7, ?)",
                (("First",), ("Conflicting",)),
            ),
            (
                "PayClasses",
                "CREATE TABLE Employees (UID INTEGER, FirstName TEXT)",
                "CREATE TABLE PayClasses (UID INTEGER, Name TEXT)",
                "INSERT INTO PayClasses VALUES (7, ?)",
                (("First",), ("Conflicting",)),
            ),
        )
        for table, employees_ddl, pay_classes_ddl, insert_sql, rows in fixtures:
            with self.subTest(table=table):
                conn = sqlite3.connect(":memory:")
                conn.execute(employees_ddl)
                conn.execute(pay_classes_ddl)
                conn.executemany(insert_sql, rows)
                reader = Reader(conn)
                with self.assertRaisesRegex(
                    RuntimeError,
                    f"{table} contains duplicate UID 7",
                ):
                    reader._parse_employees_and_pay_classes(
                        _SqliteConnectionWrapper(conn)
                    )

    def test_employee_update_rejects_duplicate_physical_uid(self):
        class EmployeeOps(_SqliteMdbOps):
            @staticmethod
            def _execute_update_values(
                cursor,
                _schema,
                table,
                values,
                _required_columns,
                where_sql,
                where_params,
                _operation,
            ):
                columns = list(values)
                assignments = ", ".join(f"[{column}]=?" for column in columns)
                cursor.execute(
                    f"UPDATE [{table}] SET {assignments} WHERE {where_sql}",
                    *[values[column] for column in columns],
                    *where_params,
                )

        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE Employees ("
            "UID INTEGER, EmployeeNo TEXT, FirstName TEXT, LastName TEXT, "
            "Address1 TEXT, Address2 TEXT, City TEXT, State TEXT, Zip TEXT, "
            "HomePhone TEXT, MobilePhone TEXT, EMail TEXT, PayClassUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO Employees (UID, EmployeeNo, FirstName) VALUES (7, ?, ?)",
            (("E1", "First"), ("E2", "Conflicting")),
        )
        employee = SimpleNamespace(
            uid="7",
            employee_no="UPDATED",
            first_name="Updated",
            last_name="",
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
        with self.assertLogs("test", level="ERROR") as logs:
            result = EmployeeOps(conn).save_employees(
                "malformed.mdb",
                {"new": [], "updated": [employee], "deleted_uids": []},
            )
        self.assertIsNone(result)
        self.assertIn("Employees contains duplicate UID 7", logs.output[0])
        self.assertEqual(
            conn.execute(
                "SELECT EmployeeNo, FirstName FROM Employees ORDER BY rowid"
            ).fetchall(),
            [("E1", "First"), ("E2", "Conflicting")],
        )

    def test_delete_employee_clears_all_direct_bid_roles(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Employees (UID INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE Bids ("
            "UID INTEGER PRIMARY KEY, EstimatorUID INTEGER, "
            "PrManagerUID INTEGER, JobSiteManagerUID INTEGER)"
        )
        conn.execute("INSERT INTO Employees VALUES (7)")
        conn.execute("INSERT INTO Bids VALUES (1, 7, 7, 7)")
        result = _SqliteMdbOps(conn).save_employees(
            "bid.mdb", {"new": [], "updated": [], "deleted_uids": ["7"]}
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute(
                "SELECT EstimatorUID, PrManagerUID, JobSiteManagerUID FROM Bids"
            ).fetchone(),
            (None, None, None),
        )

    def test_delete_employee_removes_direct_dpc_subscriber_reference(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Employees (UID INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE BidEmployees ("
            "UID INTEGER PRIMARY KEY, EmployeeUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidDPCSubscribers ("
            "UID INTEGER PRIMARY KEY, BidEmployeeUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidTimeCards ("
            "UID INTEGER PRIMARY KEY, BidEmployeeUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE ConditionSets ("
            "UID INTEGER PRIMARY KEY, EmployeeUID INTEGER)"
        )
        conn.execute("INSERT INTO Employees VALUES (7)")
        conn.execute("INSERT INTO BidEmployees VALUES (70, 7)")
        conn.execute("INSERT INTO BidDPCSubscribers VALUES (700, 7)")
        conn.execute("INSERT INTO BidTimeCards VALUES (701, 70)")
        conn.execute("INSERT INTO ConditionSets VALUES (702, 7)")
        result = _SqliteMdbOps(conn).save_employees(
            "bid.mdb", {"new": [], "updated": [], "deleted_uids": ["7"]}
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidDPCSubscribers").fetchone()[0],
            0,
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidEmployees").fetchone()[0], 0
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidTimeCards").fetchone()[0], 0
        )
        self.assertIsNone(
            conn.execute("SELECT EmployeeUID FROM ConditionSets").fetchone()[0]
        )

    def test_delete_employee_preserves_subscriber_for_colliding_bid_employee_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Employees (UID INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE BidEmployees ("
            "UID INTEGER PRIMARY KEY, EmployeeUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidDPCSubscribers ("
            "UID INTEGER PRIMARY KEY, BidEmployeeUID INTEGER)"
        )
        conn.executemany("INSERT INTO Employees VALUES (?)", [(7,), (70,)])
        conn.executemany("INSERT INTO BidEmployees VALUES (?, ?)", [(70, 7), (71, 70)])
        conn.execute("INSERT INTO BidDPCSubscribers VALUES (700, 70)")
        result = _SqliteMdbOps(conn).save_employees(
            "bid.mdb", {"new": [], "updated": [], "deleted_uids": ["7"]}
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute("SELECT BidEmployeeUID FROM BidDPCSubscribers").fetchall(),
            [(70,)],
        )
        self.assertEqual(
            conn.execute("SELECT UID, EmployeeUID FROM BidEmployees").fetchall(),
            [(71, 70)],
        )

    def test_delete_employee_cleans_dpc_subscriber_without_bid_employees_table(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Employees (UID INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE BidDPCSubscribers ("
            "UID INTEGER PRIMARY KEY, BidEmployeeUID INTEGER)"
        )
        conn.execute("INSERT INTO Employees VALUES (7)")
        conn.execute("INSERT INTO BidDPCSubscribers VALUES (700, 7)")
        result = _SqliteMdbOps(conn).save_employees(
            "legacy.mdb", {"new": [], "updated": [], "deleted_uids": ["7"]}
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidDPCSubscribers").fetchone()[0], 0
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM Employees").fetchone()[0], 0
        )

    def test_delete_pay_class_clears_global_and_bid_employee_references(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE PayClasses (UID INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE Employees (UID INTEGER PRIMARY KEY, PayClassUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidEmployees (UID INTEGER PRIMARY KEY, PayClassUID INTEGER)"
        )
        conn.execute("INSERT INTO PayClasses VALUES (7)")
        conn.execute("INSERT INTO Employees VALUES (70, 7)")
        conn.execute("INSERT INTO BidEmployees VALUES (700, 7)")
        result = _SqliteMdbOps(conn).save_pay_classes(
            "legacy.mdb", {"new": [], "updated": [], "deleted_uids": ["7"]}
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute("SELECT PayClassUID FROM Employees").fetchall(), [(None,)]
        )
        self.assertEqual(
            conn.execute("SELECT PayClassUID FROM BidEmployees").fetchall(),
            [(None,)],
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM PayClasses").fetchone()[0], 0
        )

    def test_delete_parent_takeoff_clears_child_parent_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            """
            CREATE TABLE BidTakeoffs (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                ParentUID INTEGER
            )
            """
        )
        conn.execute(
            "INSERT INTO BidTakeoffs (UID, BidUID, ParentUID) VALUES (1, 1, NULL)"
        )
        conn.execute(
            "INSERT INTO BidTakeoffs (UID, BidUID, ParentUID) VALUES (2, 1, 1)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_takeoffs("bid.mdb", ["1"]))
        child = conn.execute(
            "SELECT ParentUID FROM BidTakeoffs WHERE UID = 2"
        ).fetchone()
        self.assertIsNone(child[0])

    def test_delete_takeoff_removes_annotations_linked_by_either_endpoint(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            """
            CREATE TABLE BidTakeoffs (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                ParentUID INTEGER
            )
            """
        )
        conn.executemany(
            "INSERT INTO BidTakeoffs (UID, BidUID, ParentUID) VALUES (?, 1, NULL)",
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

    def test_takeoff_insert_reserves_dangling_annotation_endpoint_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
            "BidPageUID INTEGER, Position BLOB, ParentUID INTEGER)"
        )
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidDimensions " "(UID INTEGER, BidTakeoffFromUID INTEGER)"
        )
        conn.execute("INSERT INTO BidConditions VALUES (5, 1)")
        conn.execute("INSERT INTO BidPages VALUES (3, 1)")
        conn.execute("INSERT INTO BidTakeoffs VALUES (7, 1, 5, 3, X'00', NULL)")
        conn.execute("INSERT INTO BidDimensions VALUES (70, 8)")
        result = _SqliteDuplicateOps(conn).insert_takeoffs(
            "legacy.mdb",
            "1",
            [
                InsertTakeoffSpec(
                    condition_uid="5",
                    page_uid="3",
                    area_uid=None,
                    position=[0.0, 0.0, 1.0, 1.0],
                )
            ],
        )
        self.assertEqual(result, ["9"])
        self.assertEqual(
            conn.execute("SELECT UID FROM BidTakeoffs ORDER BY UID").fetchall(),
            [(7,), (9,)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM BidDimensions AS dimension "
                "INNER JOIN BidTakeoffs AS takeoff "
                "ON dimension.BidTakeoffFromUID=takeoff.UID"
            ).fetchone()[0],
            0,
        )

    def test_takeoff_insert_rejects_cross_bid_batch_before_any_insert(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.executemany("INSERT INTO Bids VALUES (?)", ((1,), (2,)))
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
            "BidPageUID INTEGER, BidAreaUID INTEGER, Position BLOB, ParentUID INTEGER)"
        )
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)")
        conn.executemany("INSERT INTO BidConditions VALUES (?, ?)", ((10, 1), (11, 2)))
        conn.executemany("INSERT INTO BidPages VALUES (?, ?)", ((20, 1), (21, 2)))
        conn.executemany("INSERT INTO BidAreas VALUES (?, ?)", ((30, 1), (31, 2)))
        result = _SqliteDuplicateOps(conn).insert_takeoffs(
            "malformed.mdb",
            "1",
            [
                InsertTakeoffSpec("10", "20", "30", [0.0, 0.0, 1.0, 1.0]),
                InsertTakeoffSpec("11", "20", "30", [1.0, 1.0, 2.0, 2.0]),
            ],
        )
        self.assertEqual(result, [])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidTakeoffs").fetchone()[0], 0
        )

    def test_takeoff_insert_rejects_orphan_bid_before_identity_allocation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
            "BidPageUID INTEGER, Position BLOB, ParentUID INTEGER)"
        )
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidConditions VALUES (10, 99)")
        conn.execute("INSERT INTO BidPages VALUES (20, 99)")
        with self.assertLogs("test", level="ERROR") as logs:
            result = _SqliteDuplicateOps(conn).insert_takeoffs(
                "malformed.mdb",
                "99",
                [
                    InsertTakeoffSpec(
                        condition_uid="10",
                        page_uid="20",
                        area_uid=None,
                        position=[0.0, 0.0, 1.0, 1.0],
                    )
                ],
            )
        self.assertEqual(result, [])
        self.assertIn("Bids has no row for UID 99", logs.output[0])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidTakeoffs").fetchone()[0], 0
        )

    def test_annotation_insert_rejects_orphan_bid_before_identity_allocation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidPages VALUES (20, 99)")
        conn.execute(
            "CREATE TABLE BidAnnotationRects ("
            "UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, Position BLOB, "
            "Color INTEGER, Width INTEGER)"
        )
        with self.assertLogs("test", level="ERROR") as logs:
            result = _SqliteAnnotationOps(conn).insert_annotations(
                "malformed.mdb",
                "99",
                [
                    InsertAnnotationSpec(
                        page_uid="20",
                        annotation_type="rect",
                        position=[0.0, 0.0, 1.0, 1.0],
                        color="#000000",
                        width=1.0,
                    )
                ],
            )
        self.assertEqual(result, [])
        self.assertIn("Bids has no row for UID 99", logs.output[0])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidAnnotationRects").fetchone()[0], 0
        )

    def test_bid_area_insert_rejects_orphan_bid_before_identity_allocation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidAreas ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT, "
            "Sequence INTEGER, GUID TEXT)"
        )
        with self.assertLogs("test", level="ERROR") as logs:
            result = _SqliteDuplicateOps(conn).save_bid_areas(
                "malformed.mdb",
                "99",
                BidAreaChangeset(
                    new=[BidArea("new_0", "99", "", "Area", 0)],
                    updated=[],
                    deleted_uids=[],
                ),
            )
        self.assertEqual(result, {})
        self.assertIn("Bids has no row for UID 99", logs.output[0])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidAreas").fetchone()[0], 0)

    def test_selected_page_save_rejects_orphan_bid_companion_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidSettings (BidUID INTEGER, BidPageSelectedUID INTEGER)"
        )
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidSettings VALUES (99, NULL)")
        conn.execute("INSERT INTO BidPages VALUES (20, 99)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteDuplicateOps(conn).save_bid_selected_page(
                    "malformed.mdb", "99", "20"
                )
            )
        self.assertIn("Bids has no row for UID 99", logs.output[0])
        self.assertIsNone(
            conn.execute(
                "SELECT BidPageSelectedUID FROM BidSettings WHERE BidUID=99"
            ).fetchone()[0]
        )

    def test_orphan_page_edit_and_delete_reject_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT)")
        conn.execute("INSERT INTO BidPages VALUES (7, 99, 'Legacy page')")
        ops = _SqliteDuplicateOps(conn)
        with self.assertLogs("test", level="ERROR") as edit_logs:
            self.assertFalse(ops.save_page_name("legacy.mdb", "7", "Changed"))
        self.assertIn("Bids has no row for UID 99", edit_logs.output[0])
        self.assertEqual(
            conn.execute("SELECT Name FROM BidPages WHERE UID=7").fetchone()[0],
            "Legacy page",
        )
        with self.assertLogs("test", level="ERROR") as delete_logs:
            self.assertFalse(ops.delete_pages("legacy.mdb", ["7"]))
        self.assertIn("Bids has no row for UID 99", delete_logs.output[0])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidPages").fetchone()[0], 1)

    def test_orphan_condition_edit_and_delete_reject_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, RefNo INTEGER)"
        )
        conn.execute("INSERT INTO BidConditions VALUES (7, 99, 'Legacy condition', 4)")
        ops = _SqliteDuplicateOps(conn)
        updates = UpdateConditionDto()
        updates.set("name", "Changed")
        with self.assertLogs("test", level="ERROR") as edit_logs:
            self.assertFalse(ops.update_condition("legacy.mdb", "99", "7", updates))
        self.assertIn("Bids has no row for UID 99", edit_logs.output[0])
        self.assertEqual(
            conn.execute("SELECT Name FROM BidConditions WHERE UID=7").fetchone()[0],
            "Legacy condition",
        )
        with self.assertLogs("test", level="ERROR") as renumber_logs:
            self.assertFalse(ops.renumber_conditions("legacy.mdb", "99", ["7"]))
        self.assertIn("Bids has no row for UID 99", renumber_logs.output[0])
        self.assertEqual(
            conn.execute("SELECT RefNo FROM BidConditions WHERE UID=7").fetchone()[0],
            4,
        )
        with self.assertLogs("test", level="ERROR") as delete_logs:
            self.assertFalse(ops.delete_conditions("legacy.mdb", "99", ["7"]))
        self.assertIn("Bids has no row for UID 99", delete_logs.output[0])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidConditions").fetchone()[0], 1
        )

    def test_orphan_layer_and_folder_mutations_reject_before_write(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidLayers ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, Show INTEGER)"
        )
        conn.execute("INSERT INTO BidLayers VALUES (7, 99, 'Legacy layer', 0)")
        conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        conn.execute(
            "INSERT INTO BidConditionFolders VALUES (8, 99, 'Legacy folder', NULL)"
        )
        ops = _SqliteDuplicateOps(conn)
        with self.assertRaisesRegex(RuntimeError, "Bids has no row for UID 99"):
            ops.update_layer_name("legacy.mdb", "7", "Changed")
        with self.assertRaisesRegex(RuntimeError, "Bids has no row for UID 99"):
            ops.update_all_layers_show("legacy.mdb", "99", True)
        self.assertEqual(
            conn.execute("SELECT Name, Show FROM BidLayers WHERE UID=7").fetchone(),
            ("Legacy layer", 0),
        )
        with self.assertLogs("test", level="ERROR") as rename_logs:
            self.assertFalse(ops.rename_condition_folder("legacy.mdb", "8", "Changed"))
        self.assertIn("Bids has no row for UID 99", rename_logs.output[0])
        with self.assertLogs("test", level="ERROR") as delete_logs:
            self.assertFalse(ops.delete_condition_folders("legacy.mdb", ["8"]))
        self.assertIn("Bids has no row for UID 99", delete_logs.output[0])
        self.assertEqual(
            conn.execute("SELECT Name FROM BidConditionFolders WHERE UID=8").fetchone()[
                0
            ],
            "Legacy folder",
        )

    def test_orphan_takeoff_and_annotation_mutations_reject_before_write(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, IsNegativeQuantity INTEGER)"
        )
        conn.execute("INSERT INTO BidTakeoffs VALUES (7, 99, 0)")
        conn.execute(
            "CREATE TABLE BidNamedViews (" "UID INTEGER, BidUID INTEGER, Name TEXT)"
        )
        conn.execute("INSERT INTO BidNamedViews VALUES (8, 99, 'Legacy view')")
        takeoff_ops = _SqliteDuplicateOps(conn)
        with self.assertLogs("test", level="ERROR") as takeoff_edit_logs:
            self.assertFalse(
                takeoff_ops.set_takeoffs_negative("legacy.mdb", ["7"], True)
            )
        self.assertIn("Bids has no row for UID 99", takeoff_edit_logs.output[0])
        with self.assertLogs("test", level="ERROR") as takeoff_delete_logs:
            self.assertFalse(takeoff_ops.delete_takeoffs("legacy.mdb", ["7"]))
        self.assertIn("Bids has no row for UID 99", takeoff_delete_logs.output[0])
        self.assertEqual(
            conn.execute(
                "SELECT IsNegativeQuantity FROM BidTakeoffs WHERE UID=7"
            ).fetchone()[0],
            0,
        )
        annotation_ops = _SqliteAnnotationOps(conn)
        with self.assertLogs("test", level="ERROR") as annotation_edit_logs:
            self.assertFalse(
                annotation_ops.save_annotation_text_properties(
                    "legacy.mdb", [("8", "namedview", {"Text": "Changed"})]
                )
            )
        self.assertIn("Bids has no row for UID 99", annotation_edit_logs.output[0])
        with self.assertLogs("test", level="ERROR") as annotation_delete_logs:
            self.assertFalse(
                annotation_ops.delete_annotations("legacy.mdb", [("8", "namedview")])
            )
        self.assertIn("Bids has no row for UID 99", annotation_delete_logs.output[0])
        self.assertEqual(
            conn.execute("SELECT Name FROM BidNamedViews WHERE UID=8").fetchone()[0],
            "Legacy view",
        )

    def test_cover_sheet_omits_master_fields_when_legacy_tables_are_unavailable(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE Bids ("
            "UID INTEGER, JobName TEXT, JobStatusUID INTEGER, EstimatorUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (7, 'Before', 8, 9)")
        self.assertTrue(
            _SqliteDuplicateOps(conn).save_cover_sheet(
                "legacy.mdb",
                "7",
                {"job_name": "After", "measure_base": 0},
            )
        )
        self.assertEqual(
            conn.execute(
                "SELECT JobName, JobStatusUID, EstimatorUID FROM Bids WHERE UID=7"
            ).fetchone(),
            ("After", 8, 9),
        )

    def test_cover_sheet_rejects_new_master_reference_when_table_is_unavailable(self):
        for update_key, expected_message in (
            ("job_status_uid", "JobStatuses is unavailable"),
            ("estimator_uid", "Employees is unavailable"),
        ):
            with self.subTest(update_key=update_key):
                conn = sqlite3.connect(":memory:")
                conn.execute(
                    "CREATE TABLE Bids ("
                    "UID INTEGER, JobName TEXT, JobStatusUID INTEGER, "
                    "EstimatorUID INTEGER)"
                )
                conn.execute("INSERT INTO Bids VALUES (7, 'Before', 8, 9)")
                with self.assertLogs("test", level="ERROR") as logs:
                    self.assertFalse(
                        _SqliteDuplicateOps(conn).save_cover_sheet(
                            "legacy.mdb",
                            "7",
                            {
                                "job_name": "After",
                                "measure_base": 0,
                                update_key: "10",
                            },
                        )
                    )
                self.assertIn(expected_message, logs.output[0])
                self.assertEqual(
                    conn.execute(
                        "SELECT JobName, JobStatusUID, EstimatorUID "
                        "FROM Bids WHERE UID=7"
                    ).fetchone(),
                    ("Before", 8, 9),
                )

    def test_takeoff_insert_rejects_each_cross_bid_owner(self):
        for relationship in ("condition", "page", "area", "parent"):
            with self.subTest(relationship=relationship):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE Bids (UID INTEGER)")
                conn.executemany("INSERT INTO Bids VALUES (?)", ((1,), (2,)))
                conn.execute(
                    "CREATE TABLE BidTakeoffs ("
                    "UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
                    "BidPageUID INTEGER, BidAreaUID INTEGER, Position BLOB, "
                    "ParentUID INTEGER)"
                )
                conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
                conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
                conn.execute("CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)")
                conn.executemany(
                    "INSERT INTO BidConditions VALUES (?, ?)", ((10, 1), (11, 2))
                )
                conn.executemany(
                    "INSERT INTO BidPages VALUES (?, ?)", ((20, 1), (21, 2))
                )
                conn.executemany(
                    "INSERT INTO BidAreas VALUES (?, ?)", ((30, 1), (31, 2))
                )
                conn.execute(
                    "INSERT INTO BidTakeoffs VALUES (40, 2, 11, 21, 31, X'00', NULL)"
                )
                condition_uid = "11" if relationship == "condition" else "10"
                page_uid = "21" if relationship == "page" else "20"
                area_uid = "31" if relationship == "area" else "30"
                parent_uid = "40" if relationship == "parent" else None
                result = _SqliteDuplicateOps(conn).insert_takeoffs(
                    "malformed.mdb",
                    "1",
                    [
                        InsertTakeoffSpec(
                            condition_uid,
                            page_uid,
                            area_uid,
                            [0.0, 0.0, 1.0, 1.0],
                            parent_uid=parent_uid,
                        )
                    ],
                )
                self.assertEqual(result, [])
                self.assertEqual(
                    conn.execute("SELECT UID FROM BidTakeoffs ORDER BY UID").fetchall(),
                    [(40,)],
                )

    def test_takeoff_relationship_updates_reject_cross_bid_sets_atomically(self):
        for method_name, target_uid, expected_column in (
            ("save_takeoffs_condition", "11", "BidConditionUID"),
            ("save_takeoffs_area", "31", "BidAreaUID"),
        ):
            with self.subTest(method=method_name):
                conn = sqlite3.connect(":memory:")
                conn.execute(
                    "CREATE TABLE BidTakeoffs ("
                    "UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
                    "BidAreaUID INTEGER)"
                )
                conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
                conn.execute("CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)")
                conn.executemany(
                    "INSERT INTO BidTakeoffs VALUES (?, ?, 10, 30)",
                    ((1, 1), (2, 2)),
                )
                conn.executemany(
                    "INSERT INTO BidConditions VALUES (?, ?)", ((10, 1), (11, 2))
                )
                conn.executemany(
                    "INSERT INTO BidAreas VALUES (?, ?)", ((30, 1), (31, 2))
                )
                operations = _SqliteDuplicateOps(conn)
                if method_name == "save_takeoffs_condition":
                    result = operations.save_takeoffs_condition(
                        "malformed.mdb", ["1", "2"], target_uid
                    )
                else:
                    result = operations.save_takeoffs_area(
                        "malformed.mdb", ["1", "2"], target_uid
                    )
                self.assertFalse(result)
                self.assertEqual(
                    conn.execute(
                        f"SELECT [{expected_column}] FROM BidTakeoffs ORDER BY UID"
                    ).fetchall(),
                    [
                        (10 if expected_column == "BidConditionUID" else 30,),
                        (10 if expected_column == "BidConditionUID" else 30,),
                    ],
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

            def column_exists(self, _table, column):
                return column in {"UID", "BidUID", "Name"}

        class FakeCursor:
            def __init__(self):
                self.calls = []
                self.validation_rows = []

            def execute(self, sql, *params):
                if sql.startswith("SELECT [UID], [BidUID] FROM ["):
                    self.validation_rows = [(param, 1) for param in params]
                    return
                if sql.startswith("SELECT [UID] FROM ["):
                    self.validation_rows = [(param,) for param in params]
                    return
                self.calls.append((sql, params))

            def fetchall(self):
                return list(self.validation_rows)

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
        self.assertEqual(
            writer.required_columns,
            [
                ("BidNamedViews", ("UID", "BidUID")),
                ("BidNamedViews", ("UID", "Name")),
            ],
        )
        sql, params = writer.connection.cursor_instance.calls[0]
        self.assertIn("UPDATE [BidNamedViews] SET [Name]=?", sql)
        self.assertEqual(params, ("New View", 42))


if __name__ == "__main__":
    unittest.main()
