import os
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from contextlib import contextmanager
from typing import Optional
from unittest.mock import patch
import pyodbc
from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    ResourceRef,
)
from ost_visualizer.application.services.base_write_service import (
    DatabaseMutationWriteService,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.file_results import FileLoadResult
from ost_visualizer.domain.entities.hierarchy_data import HierarchyFileEntry
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.writer_router import DatabaseProjectWriter
from ost_visualizer.infrastructure.mdb.connection_manager import MdbConnectionManager
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from tests.paths import REPO_ROOT
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from ost_visualizer.infrastructure.persistence.repositories.file_project_repository import (
    FileProjectRepository,
    MdbFileParser,
)


class _LifecycleCounts:
    def __init__(self) -> None:
        self.connections_opened = 0
        self.connections_closed = 0
        self.active_connections = 0
        self.cursors_created = 0
        self.cursors_closed = 0
        self.active_cursors = 0
        self.max_active_cursors = 0
        self.commits = 0
        self.rollbacks = 0
        self.connections = []
        self.committed_rows = []


class _FakeCursor:
    def __init__(self, connection: "_FakeConnection") -> None:
        self._connection = connection
        self._counts = connection.counts
        self._closed = False
        self._rows = [("row",)]
        connection.open_cursors.append(self)
        self.rowcount = -1
        self._counts.cursors_created += 1
        self._counts.active_cursors += 1
        self._counts.max_active_cursors = max(
            self._counts.max_active_cursors, self._counts.active_cursors
        )

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        # pyodbc cursor context managers commit or roll back; they do not close.
        pass

    def execute(self, sql: str):
        if sql == "RAISE_QUERY_ERROR":
            self._connection.unhealthy = True
            raise pyodbc.OperationalError("08S01", "connection failed")
        if sql == "RAISE_CONNECTION_CLASS_ERROR":
            raise pyodbc.OperationalError("08S01", "communication link failed")
        if sql == "RAISE_SCHEMA_ERROR":
            raise pyodbc.ProgrammingError("42S02", "table does not exist")
        if sql == "RAISE_TRANSIENT_STATEMENT_ERROR":
            raise pyodbc.OperationalError("HY000", "statement temporarily failed")
        if sql == "INSERT_PENDING":
            self._connection.pending_rows.append("pending")
        if sql == "SELECT_VISIBLE_ROWS":
            self._rows = [
                (row,)
                for row in (self._counts.committed_rows + self._connection.pending_rows)
            ]
        return self

    def fetchall(self):
        return self._rows

    def close(self) -> None:
        if self._closed:
            return
        if self._connection.fail_next_cursor_close:
            self._connection.fail_next_cursor_close = False
            raise pyodbc.OperationalError("HY000", "cursor close failed")
        self._force_close()

    def _force_close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._counts.cursors_closed += 1
        self._counts.active_cursors -= 1
        if self in self._connection.open_cursors:
            self._connection.open_cursors.remove(self)


class _FakeConnection:
    def __init__(
        self,
        counts: _LifecycleCounts,
        connection_string: str,
        autocommit: bool,
        max_active_cursors: Optional[int] = None,
    ) -> None:
        self.counts = counts
        self.connection_string = connection_string
        self.autocommit = autocommit
        self.max_active_cursors = max_active_cursors
        self.closed = False
        self.unhealthy = False
        self.fail_rollback_once = False
        self.pending_rows = []
        self.fail_next_cursor_close = False
        self.open_cursors = []
        self.owner_thread_id = threading.get_ident()
        counts.connections_opened += 1
        counts.active_connections += 1
        counts.connections.append(self)

    def cursor(self):
        if self.closed or self.unhealthy:
            raise pyodbc.OperationalError("08S01", "connection is closed")
        if (
            self.max_active_cursors is not None
            and self.counts.active_cursors >= self.max_active_cursors
        ):
            raise pyodbc.OperationalError("Cannot open any more tables")
        return _FakeCursor(self)

    def commit(self) -> None:
        self.counts.commits += 1
        self.counts.committed_rows.extend(self.pending_rows)
        self.pending_rows.clear()

    def rollback(self) -> None:
        self.counts.rollbacks += 1
        if self.fail_rollback_once:
            self.fail_rollback_once = False
            self.unhealthy = True
            raise pyodbc.OperationalError("08S01", "rollback failed")
        self.pending_rows.clear()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.pending_rows.clear()
        for cursor in list(self.open_cursors):
            cursor._force_close()
        self.counts.connections_closed += 1
        self.counts.active_connections -= 1

    def getinfo(self, _info_type):
        return self.connection_string


class _FakeConnect:
    def __init__(self) -> None:
        self.counts = _LifecycleCounts()
        self.connect_attempts = 0
        self.max_opens = None
        self.max_active_cursors = None

    def __call__(self, connection_string: str, *, autocommit: bool):
        self.connect_attempts += 1
        if (
            self.max_opens is not None
            and self.counts.connections_opened >= self.max_opens
        ):
            raise pyodbc.OperationalError(
                "08004",
                "[Microsoft][ODBC Microsoft Access Driver] "
                "Too many client tasks. (-1036) (SQLDriverConnect)",
            )
        return _FakeConnection(
            self.counts,
            connection_string,
            autocommit,
            max_active_cursors=self.max_active_cursors,
        )


class _MaterializingRawBidReader(MdbReader):
    def _select_all_single(self, _connection, table, key_col, key_val):
        return {key_col: key_val, "Table": table}

    def _select_all_filtered(self, _connection, table, key_col, key_val):
        if table == "BidPages":
            return [{"UID": "page-1", key_col: key_val}]
        return [{key_col: key_val, "Table": table}]

    def _select_all_by_bid_or_page(self, _connection, table, bid_uid, page_uids):
        return [{"BidUID": bid_uid, "PageUID": page_uids[0], "Table": table}]

    def _select_all_unfiltered(self, _connection, table):
        return [{"Table": table}]


class _ConnectionCountingParser:
    def __init__(self, manager: MdbConnectionManager) -> None:
        self._manager = manager

    def parse(self, file_path: str) -> FileLoadResult:
        with self._manager.connection(file_path):
            pass
        return FileLoadResult(
            success=True,
            parsed_hierarchy=HierarchyFileEntry(file_path=file_path),
        )

    def refresh_connection(self, file_path: str) -> None:
        self._manager.close_database(file_path)

    def close_connection(self, file_path=None) -> None:
        if file_path is None:
            self._manager.close()
        else:
            self._manager.close_database(file_path)


class _MutationScope:
    def __init__(self) -> None:
        self.applied = []

    @contextmanager
    def mutation_scope(self, _database_id):
        yield

    def ensure_resources_loaded(self, _database_id, _resources):
        pass

    def expected_versions(self, _database_id, _resources):
        return {}

    def apply_result(self, database_id, versions):
        self.applied.append((database_id, versions))


class MdbConnectionWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connect = _FakeConnect()
        self.connect_patch = patch(
            "ost_visualizer.infrastructure.mdb.connection_manager.pyodbc.connect",
            self.connect,
        )
        self.connect_patch.start()

    def tearDown(self) -> None:
        self.connect_patch.stop()

    def assert_cursors_released(self) -> None:
        counts = self.connect.counts
        self.assertEqual(counts.cursors_created, counts.cursors_closed)
        self.assertEqual(counts.active_cursors, 0)

    def assert_all_resources_released(self) -> None:
        counts = self.connect.counts
        self.assertEqual(counts.connections_opened, counts.connections_closed)
        self.assertEqual(counts.active_connections, 0)
        self.assert_cursors_released()

    def test_repeated_explicit_full_refresh_reopens_connection_incarnation(self):
        self.connect.max_opens = 2000
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        parser = MdbFileParser(parser=_MaterializingRawBidReader(conn_manager=manager))
        with manager.connection("refresh.mdb"):
            pass
        for _index in range(500):
            with writer._connection("refresh.mdb"):
                pass
            manager.close_database("refresh.mdb")
            raw_data = parser.get_raw_bid_data("refresh.mdb", "bid-1")
            self.assertEqual(raw_data.bid_row["UID"], "bid-1")
        self.assertEqual(self.connect.counts.connections_opened, 1001)
        self.assertEqual(self.connect.counts.active_connections, 1)
        self.assertEqual(len(manager._read_conns), 1)
        self.assertEqual(len(manager._write_conns), 0)
        self.assertEqual(self.connect.counts.rollbacks, 0)
        manager.close()
        self.assert_all_resources_released()

    def test_repeated_local_write_reloads_reuse_two_physical_connections(self):
        self.connect.max_opens = 3
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        repository = FileProjectRepository(_ConnectionCountingParser(manager))
        self.assertTrue(repository.load_file("long-session.mdb").success)
        for _index in range(100):
            with writer._connection("long-session.mdb"):
                pass
        for _operation_kind in ("page", "condition"):
            for _index in range(100):
                with writer._connection("long-session.mdb"):
                    pass
                result = repository.reload_database(
                    "long-session.mdb",
                    close_connections=False,
                )
                self.assertTrue(result.success)
        self.assertEqual(self.connect.counts.connections_opened, 2)
        self.assertEqual(self.connect.connect_attempts, 2)
        self.assertEqual(self.connect.counts.active_connections, 2)
        manager.close()
        self.assert_all_resources_released()

    def test_explicit_reload_still_reopens_database_incarnation(self):
        manager = MdbConnectionManager()
        repository = FileProjectRepository(_ConnectionCountingParser(manager))
        self.assertTrue(repository.load_file("external-refresh.mdb").success)
        first_connection = next(iter(manager._read_conns.values()))
        result = repository.reload_database("external-refresh.mdb")
        self.assertTrue(result.success)
        self.assertTrue(first_connection.closed)
        self.assertEqual(self.connect.counts.connections_opened, 2)
        self.assertEqual(self.connect.counts.active_connections, 1)
        manager.close()
        self.assert_all_resources_released()

    def test_explicit_reload_after_many_writes_reopens_each_handle_once(self):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        repository = FileProjectRepository(_ConnectionCountingParser(manager))
        path = "long-reuse-refresh.mdb"
        self.assertTrue(repository.load_file(path).success)
        for _index in range(100):
            with writer._connection(path):
                pass
        path_key = os.path.normcase(os.path.abspath(path))
        old_read = manager._read_conns[path_key]
        old_write = manager._write_conns[path_key]
        self.assertEqual(self.connect.counts.connections_opened, 2)
        self.assertTrue(repository.reload_database(path).success)
        self.assertTrue(old_read.closed)
        self.assertTrue(old_write.closed)
        self.assertEqual(self.connect.counts.connections_opened, 3)
        with writer._connection(path):
            pass
        self.assertEqual(self.connect.counts.connections_opened, 4)
        self.assertIsNot(manager._read_conns[path_key], old_read)
        self.assertIsNot(manager._write_conns[path_key], old_write)
        manager.close()
        self.assert_all_resources_released()

    def test_ordinary_reload_after_failed_write_keeps_healthy_reader(self):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        repository = FileProjectRepository(_ConnectionCountingParser(manager))
        path = "failed-write-reload.mdb"
        path_key = os.path.normcase(os.path.abspath(path))
        self.assertTrue(repository.load_file(path).success)
        original_reader = manager._read_conns[path_key]
        with self.assertRaisesRegex(pyodbc.OperationalError, "connection failed"):
            with writer._connection(path) as connection:
                connection.cursor().execute("RAISE_QUERY_ERROR")
        self.assertTrue(
            repository.reload_database(path, close_connections=False).success
        )
        self.assertIs(manager._read_conns[path_key], original_reader)
        with writer._connection(path):
            pass
        self.assertEqual(self.connect.counts.connections_opened, 3)
        manager.close()
        self.assert_all_resources_released()

    def test_routed_access_mutation_translates_driver_exhaustion_before_operation(self):
        self.connect.max_opens = 0
        manager = MdbConnectionManager()
        registry = DatabaseDescriptorRegistry()
        session_registry = type(
            "SessionRegistry",
            (),
            {
                "get": lambda _self, _database_id: None,
                "lock_tokens": lambda _self, _database_id, _resources: (),
            },
        )()
        writer = DatabaseProjectWriter(
            manager,
            registry,
            object(),
            session_registry,
        )
        concurrency = _MutationScope()
        service = DatabaseMutationWriteService(
            reload_database=lambda _database_id: True,
            event_bus=type(
                "EventBus", (), {"publish": lambda *_args, **_kwargs: None}
            )(),
            mutation_executor=writer,
            session_registry=session_registry,
            concurrency_tokens=concurrency,
            database_capability_service=type(
                "Capability",
                (),
                {"is_editable": lambda _self, _database_id, _resource=None: True},
            )(),
        )
        operation_calls = []
        result = service._execute_database_mutation(
            "exhausted.mdb",
            (ResourceRef("takeoffs_collection", "7", 7),),
            lambda _recorder: operation_calls.append(True),
            operation_id=str(uuid.uuid4()),
        )
        self.assertEqual(
            result.outcome_status,
            MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
        )
        self.assertIn("restart OST Visualizer", result.failure_reason)
        self.assertEqual(operation_calls, [])
        self.assertEqual(self.connect.connect_attempts, 1)
        self.assertEqual(concurrency.applied, [])

    def test_repeated_export_preparation_materializes_before_releasing_lease(self):
        manager = MdbConnectionManager()
        parser = MdbFileParser(parser=_MaterializingRawBidReader(conn_manager=manager))
        for _index in range(500):
            raw_data = parser.get_raw_bid_data("export.mdb", "bid-1")
            self.assertEqual(raw_data.bid_row["UID"], "bid-1")
            self.assertEqual(raw_data.bid_tables["BidPages"][0]["UID"], "page-1")
        self.assertEqual(self.connect.counts.connections_opened, 1)
        self.assertEqual(self.connect.counts.active_connections, 1)
        manager.close()
        self.assert_all_resources_released()

    def test_failed_export_preparation_releases_lease(self):
        class FailingReader(_MaterializingRawBidReader):
            def _select_all_single(self, *_args):
                raise ValueError("serialization failed")

        manager = MdbConnectionManager()
        parser = MdbFileParser(parser=FailingReader(conn_manager=manager))
        with self.assertRaisesRegex(ValueError, "serialization failed"):
            parser.get_raw_bid_data("failed-export.mdb", "bid-1")
        self.assert_cursors_released()
        manager.close()
        self.assert_all_resources_released()


try:
    import pythoncom
    import win32com.client
except ImportError:  # pragma: no cover - pywin32 ships with the project venv
    pythoncom = None
    win32com = None


def _create_real_access_database(test_case, directory, statements):
    """Create a real .mdb through DAO, or skip when Access DAO is unavailable."""
    if pythoncom is None:
        test_case.skipTest("pywin32 is unavailable")
    pythoncom.CoInitialize()
    test_case.addCleanup(pythoncom.CoUninitialize)
    try:
        engine = win32com.client.Dispatch("DAO.DBEngine.120")
    except pythoncom.com_error as exc:
        test_case.skipTest(f"Access DAO unavailable: {exc.hresult}")
    path = os.path.join(directory, "real.mdb")
    database = engine.CreateDatabase(path, ";LANGID=0x0409;CP=1252;COUNTRY=0", 64)
    try:
        for statement in statements:
            database.Execute(statement)
    finally:
        database.Close()
    return path


class RealAccessConnectionWorkflowTests(unittest.TestCase):
    """Second-pass: the same lifecycle rules against the real Access ODBC driver.
    ACE keeps process-level client tasks alive even after ODBC connections are
    closed and fails with 08004/-1036 after roughly sixty connections in one
    process; the integration suite already sits at that ceiling. The scenarios
    therefore run in a child process (like
    SchemaAcceptanceCompatibilityTests.test_zz_duplicate_bid_round_trip...)
    and are driven by the single collected test below. Scenario methods are
    deliberately not named ``test_*`` so discovery never runs them in-process.
    """

    SCENARIOS = (
        "scenario_rollback_discards_pending_rows_and_keeps_the_writer_handle",
        "scenario_statement_errors_roll_back_the_mutation_and_keep_handles",
        "scenario_database_close_releases_read_and_write_handles",
        "scenario_routed_uid_allocation_is_reference_safe_but_sql_is_deferred",
    )
    _STATEMENTS = (
        "CREATE TABLE Items (UID LONG CONSTRAINT ItemsPK PRIMARY KEY, Name TEXT(50))",
        "CREATE TABLE BidPages (UID LONG, MasterPageUID LONG)",
        "INSERT INTO BidPages VALUES (7, 12)",
    )

    def _database(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return _create_real_access_database(self, directory.name, self._STATEMENTS)

    @staticmethod
    def _item_names(manager, path):
        with manager.connection(path) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT Name FROM Items ORDER BY UID")
                return [row[0] for row in cursor.fetchall()]

    def scenario_rollback_discards_pending_rows_and_keeps_the_writer_handle(
        self,
    ):
        path = self._database()
        manager = MdbConnectionManager()
        self.addCleanup(manager.close)
        writer = MdbWriter(conn_manager=manager)
        key = os.path.normcase(os.path.abspath(path))
        with writer._connection(path) as connection:
            connection.cursor().execute("INSERT INTO Items VALUES (1, 'kept')")
        write_handle = manager._write_conns[key]
        with self.assertRaisesRegex(ValueError, "validation failed"):
            with writer._connection(path) as connection:
                connection.cursor().execute("INSERT INTO Items VALUES (2, 'pending')")
                raise ValueError("validation failed")
        # Successful rollback + passing health probe: the handle is reused.
        self.assertIs(manager._write_conns[key], write_handle)
        self.assertEqual(self._item_names(manager, path), ["kept"])
        with writer._connection(path) as connection:
            connection.cursor().execute("INSERT INTO Items VALUES (3, 'next')")
        self.assertIs(manager._write_conns[key], write_handle)
        self.assertEqual(self._item_names(manager, path), ["kept", "next"])

    def scenario_statement_errors_roll_back_the_mutation_and_keep_handles(self):
        path = self._database()
        manager = MdbConnectionManager()
        self.addCleanup(manager.close)
        writer = MdbWriter(conn_manager=manager)
        key = os.path.normcase(os.path.abspath(path))
        self.assertEqual(self._item_names(manager, path), [])
        read_handle = manager._read_conns[key]
        with writer._connection(path) as connection:
            connection.cursor().execute("INSERT INTO Items VALUES (1, 'kept')")
        write_handle = manager._write_conns[key]
        # Constraint violation (SQLSTATE 23000) on the second statement dooms
        # the whole Access mutation, including the first statement.
        with self.assertRaises(pyodbc.IntegrityError) as constraint:
            with writer._connection(path) as connection:
                cursor = connection.cursor()
                cursor.execute("INSERT INTO Items VALUES (2, 'doomed')")
                cursor.execute("INSERT INTO Items VALUES (1, 'duplicate')")
        self.assertEqual(constraint.exception.args[0], "23000")
        self.assertIs(manager._write_conns[key], write_handle)
        # Schema error (SQLSTATE 42S02) on a read lease is a statement error.
        with self.assertRaises(pyodbc.ProgrammingError) as missing:
            with manager.connection(path) as connection:
                connection.cursor().execute("SELECT * FROM MissingTable")
        self.assertEqual(missing.exception.args[0], "42S02")
        self.assertEqual(self._item_names(manager, path), ["kept"])
        self.assertIs(manager._read_conns[key], read_handle)
        with writer._connection(path) as connection:
            connection.cursor().execute("INSERT INTO Items VALUES (4, 'after')")
        self.assertIs(manager._write_conns[key], write_handle)
        self.assertEqual(self._item_names(manager, path), ["kept", "after"])
        self.assertIs(manager._read_conns[key], read_handle)

    def scenario_database_close_releases_read_and_write_handles(self):
        path = self._database()
        manager = MdbConnectionManager()
        self.addCleanup(manager.close)
        writer = MdbWriter(conn_manager=manager)
        key = os.path.normcase(os.path.abspath(path))
        self.assertEqual(self._item_names(manager, path), [])
        with writer._connection(path) as connection:
            connection.cursor().execute("INSERT INTO Items VALUES (1, 'kept')")
        self.assertEqual([*manager._read_conns, *manager._write_conns], [key, key])
        old_handles = (manager._read_conns[key], manager._write_conns[key])
        manager.close_database(path.upper())
        self.assertEqual((manager._read_conns, manager._write_conns), ({}, {}))
        for handle in old_handles:
            with self.assertRaises(pyodbc.ProgrammingError):
                handle.cursor()
        self.assertEqual(self._item_names(manager, path), ["kept"])
        self.assertIsNot(manager._read_conns[key], old_handles[0])

    def scenario_routed_uid_allocation_is_reference_safe_but_sql_is_deferred(
        self,
    ):
        path = self._database()
        manager = MdbConnectionManager()
        self.addCleanup(manager.close)
        sql_registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        sql_registry.register(descriptor)
        writer = DatabaseProjectWriter(manager, sql_registry, object(), object())
        with manager.connection(path) as connection:
            statements = []

            class _RecordingCursor:
                def __init__(self, cursor):
                    self._cursor = cursor

                def execute(self, sql, *params):
                    statements.append(sql)
                    self._cursor.execute(sql, *params)
                    return self

                def fetchone(self):
                    return self._cursor.fetchone()

            with connection.cursor() as raw_cursor:
                cursor = _RecordingCursor(raw_cursor)
                schema = None
                with writer._backend_scope(path):
                    schema = writer._schema(connection)
                    # BidPages.MasterPageUID already names UID 12 although the
                    # largest stored UID is 7: the Access range starts at 13.
                    self.assertEqual(writer._next_uid(cursor, "BidPages"), 8)
                    self.assertEqual(
                        writer._next_uid_preserving_references(
                            cursor, schema, "BidPages"
                        ),
                        13,
                    )
                    self.assertEqual(
                        list(
                            writer._next_uids_preserving_references(
                                cursor, schema, "BidPages", 3
                            )
                        ),
                        [13, 14, 15],
                    )
                access_statements = list(statements)
                del statements[:]
                with writer._backend_scope(descriptor.database_id):
                    deferred = writer._next_uids_preserving_references(
                        cursor, schema, "BidPages", 3
                    )
                    single = writer._next_uid_preserving_references(
                        cursor, schema, "BidPages"
                    )
                    plain = writer._next_uid(cursor, "BidPages")
        # Three allocator calls: the batch of three UIDs costs one scan.
        self.assertEqual(
            access_statements.count("SELECT MAX([UID]) FROM [BidPages]"), 3
        )
        self.assertEqual(
            access_statements.count("SELECT MAX([MasterPageUID]) FROM [BidPages]"), 2
        )
        # SQL Server identities are database generated: no MAX scan at all.
        self.assertEqual(statements, [])
        self.assertEqual(len(deferred), 3)
        for identity in (*deferred, single, plain):
            with self.assertRaisesRegex(RuntimeError, "has not been generated"):
                str(identity)

    def test_real_access_scenarios_run_in_an_isolated_process(self):
        code = (
            "import sys, unittest; "
            "from tests.integration.mdb.test_connection_workflows import "
            "RealAccessConnectionWorkflowTests as Scenarios; "
            "suite = unittest.TestSuite(map(Scenarios, Scenarios.SCENARIOS)); "
            "result = unittest.TextTestRunner(verbosity=2).run(suite); "
            "sys.exit(0 if result.wasSuccessful() else 1)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        for name in self.SCENARIOS:
            self.assertRegex(output, rf"{name} .*\.\.\. (ok|skipped)")
        if "skipped" in output:
            self.skipTest(
                "Access DAO unavailable in the child process: " + output[-300:]
            )
