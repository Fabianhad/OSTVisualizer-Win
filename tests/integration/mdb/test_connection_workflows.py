import os
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
from ost_visualizer.domain.entities.file_results import FileLoadResult
from ost_visualizer.domain.entities.hierarchy_data import HierarchyFileEntry
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.writer_router import DatabaseProjectWriter
from ost_visualizer.infrastructure.mdb.connection_manager import MdbConnectionManager
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
