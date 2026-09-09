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
from ost_visualizer.application.interfaces.i_mdb_connection_manager import (
    DatabaseConnectionUnavailableError,
)
from ost_visualizer.application.services.base_write_service import (
    DatabaseMutationWriteService,
)
from ost_visualizer.domain.entities.file_results import FileLoadResult
from ost_visualizer.domain.entities.hierarchy_data import HierarchyFileEntry
from ost_visualizer.infrastructure.mdb.connection_manager import (
    MdbConnectionManager,
)
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.reader_router import DatabaseProjectReader
from ost_visualizer.infrastructure.database.writer_router import DatabaseProjectWriter
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


class _UnavailableMutationExecutor:
    def __init__(self, message: str) -> None:
        self.message = message
        self.calls = 0

    def execute(self, _request, _operation):
        self.calls += 1
        raise DatabaseConnectionUnavailableError(self.message)


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


class MdbConnectionManagerLifecycleTests(unittest.TestCase):
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

    def test_successful_read_releases_cursor_and_shutdown_closes_cache(self):
        manager = MdbConnectionManager()
        with manager.connection("read.mdb") as connection:
            with connection.cursor() as cursor:
                self.assertEqual(cursor.execute("SELECT").fetchall(), [("row",)])
        self.assert_cursors_released()
        self.assertEqual(self.connect.counts.connections_opened, 1)
        self.assertEqual(self.connect.counts.active_connections, 1)
        manager.close()
        self.assert_all_resources_released()

    def test_successful_write_commits_and_releases_cursor(self):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        with writer._connection("write.mdb") as connection:
            connection.cursor().execute("UPDATE")
        self.assertEqual(self.connect.counts.commits, 1)
        self.assertEqual(self.connect.counts.rollbacks, 0)
        self.assert_cursors_released()
        manager.close()
        self.assert_all_resources_released()

    def test_read_after_successful_write_resets_snapshot_without_reopening(self):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        reader = MdbReader(conn_manager=manager)
        path = "reader-snapshot.mdb"
        path_key = os.path.normcase(os.path.abspath(path))
        with manager.connection(path):
            pass
        reader_connection = manager._read_conns[path_key]
        with writer._connection(path):
            pass
        writer_connection = manager._write_conns[path_key]
        with reader._connection(path) as connection:
            self.assertIs(connection._conn, writer_connection)
        self.assertIs(manager._read_conns[path_key], reader_connection)
        self.assertFalse(reader_connection.closed)
        self.assertEqual(self.connect.counts.connections_opened, 2)
        self.assertEqual(self.connect.counts.rollbacks, 1)
        manager.close()
        self.assert_all_resources_released()

    def test_failed_write_rolls_back_and_releases_cursor_and_connection(self):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        with self.assertRaisesRegex(pyodbc.OperationalError, "connection failed"):
            with writer._connection("write-error.mdb") as connection:
                connection.cursor().execute("RAISE_QUERY_ERROR")
        self.assertEqual(self.connect.counts.commits, 0)
        self.assertEqual(self.connect.counts.rollbacks, 1)
        self.assert_all_resources_released()

    def test_schema_error_rolls_back_and_reuses_healthy_writer(self):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        with self.assertRaisesRegex(pyodbc.ProgrammingError, "table does not exist"):
            with writer._connection("schema-error.mdb") as connection:
                connection.cursor().execute("RAISE_SCHEMA_ERROR")
        with writer._connection("schema-error.mdb") as connection:
            connection.cursor().execute("UPDATE")
        self.assertEqual(self.connect.counts.connections_opened, 1)
        self.assertEqual(self.connect.counts.rollbacks, 1)
        self.assertEqual(self.connect.counts.commits, 1)
        manager.close()
        self.assert_all_resources_released()

    def test_transient_statement_error_reuses_writer_after_successful_rollback(self):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        with self.assertRaisesRegex(pyodbc.OperationalError, "temporarily failed"):
            with writer._connection("transient-error.mdb") as connection:
                connection.cursor().execute("RAISE_TRANSIENT_STATEMENT_ERROR")
        with writer._connection("transient-error.mdb") as connection:
            connection.cursor().execute("UPDATE")
        self.assertEqual(self.connect.counts.connections_opened, 1)
        self.assertEqual(self.connect.counts.rollbacks, 1)
        self.assertEqual(self.connect.counts.commits, 1)
        manager.close()
        self.assert_all_resources_released()

    def test_connection_class_error_evicts_even_when_cursor_probe_would_succeed(self):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        with self.assertRaisesRegex(pyodbc.OperationalError, "communication link"):
            with writer._connection("connection-class-error.mdb") as connection:
                connection.cursor().execute("RAISE_CONNECTION_CLASS_ERROR")
        with writer._connection("connection-class-error.mdb"):
            pass
        self.assertEqual(self.connect.counts.connections_opened, 2)
        self.assertEqual(self.connect.counts.connections_closed, 1)
        manager.close()
        self.assert_all_resources_released()

    def test_failed_rollback_evicts_writer_before_next_mutation(self):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        with writer._connection("rollback-error.mdb") as connection:
            first_connection = connection._conn
        first_connection.fail_rollback_once = True
        with self.assertRaisesRegex(pyodbc.OperationalError, "rollback failed"):
            with writer._connection("rollback-error.mdb") as connection:
                connection.cursor().execute("INSERT_PENDING")
                raise ValueError("validation failed after statement")
        with writer._connection("rollback-error.mdb") as connection:
            self.assertIsNot(connection._conn, first_connection)
            visible = connection.cursor().execute("SELECT_VISIBLE_ROWS").fetchall()
            self.assertEqual(visible, [])
        self.assertTrue(first_connection.closed)
        self.assertEqual(self.connect.counts.connections_opened, 2)
        self.assertEqual(self.connect.counts.committed_rows, [])
        manager.close()
        self.assert_all_resources_released()

    def test_successful_rollback_clears_pending_state_before_writer_reuse(self):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        with self.assertRaisesRegex(ValueError, "validation failed"):
            with writer._connection("rollback-reuse.mdb") as connection:
                connection.cursor().execute("INSERT_PENDING")
                raise ValueError("validation failed")
        with writer._connection("rollback-reuse.mdb") as connection:
            visible = connection.cursor().execute("SELECT_VISIBLE_ROWS").fetchall()
            self.assertEqual(visible, [])
        self.assertEqual(self.connect.counts.connections_opened, 1)
        self.assertEqual(self.connect.counts.rollbacks, 1)
        manager.close()
        self.assert_all_resources_released()

    def test_query_exception_closes_cursor_and_invalidates_connection(self):
        manager = MdbConnectionManager()
        with self.assertRaisesRegex(pyodbc.OperationalError, "connection failed"):
            with manager.connection("query-error.mdb") as connection:
                connection.cursor().execute("RAISE_QUERY_ERROR")
        self.assert_all_resources_released()
        with manager.connection("query-error.mdb") as connection:
            connection.cursor().execute("SELECT")
        self.assertEqual(self.connect.counts.connections_opened, 2)
        manager.close()
        self.assert_all_resources_released()

    def test_failed_cursor_cleanup_evicts_connection_before_reuse(self):
        manager = MdbConnectionManager()
        with manager.connection("cursor-close-error.mdb") as connection:
            first_connection = connection._conn
            first_connection.fail_next_cursor_close = True
            connection.cursor().execute("SELECT")
        self.assertTrue(first_connection.closed)
        self.assertEqual(self.connect.counts.active_cursors, 0)
        self.assertEqual(manager._read_conns, {})
        with manager.connection("cursor-close-error.mdb") as connection:
            self.assertIsNot(connection._conn, first_connection)
        self.assertEqual(self.connect.counts.connections_opened, 2)
        manager.close()
        self.assert_all_resources_released()

    def test_failed_unhealthy_close_is_retried_before_connection_reuse(self):
        manager = MdbConnectionManager()
        close_attempts = []
        with manager.connection("cursor-close-retry.mdb") as connection:
            first_connection = connection._conn
            original_close = first_connection.close

            def fail_close_once():
                close_attempts.append(True)
                if len(close_attempts) == 1:
                    raise pyodbc.OperationalError("HY000", "connection close failed")
                original_close()

            first_connection.close = fail_close_once
            first_connection.fail_next_cursor_close = True
            connection.cursor().execute("SELECT")
        self.assertFalse(first_connection.closed)
        self.assertIn(id(first_connection), manager._unhealthy_connection_ids)
        with manager.connection("cursor-close-retry.mdb") as connection:
            self.assertIsNot(connection._conn, first_connection)
        self.assertTrue(first_connection.closed)
        self.assertEqual(len(close_attempts), 2)
        self.assertEqual(self.connect.counts.connections_opened, 2)
        manager.close()
        self.assert_all_resources_released()

    def test_read_statement_error_reuses_healthy_connection(self):
        manager = MdbConnectionManager()
        with self.assertRaisesRegex(pyodbc.ProgrammingError, "table does not exist"):
            with manager.connection("read-schema-error.mdb") as connection:
                connection.cursor().execute("RAISE_SCHEMA_ERROR")
        with manager.connection("read-schema-error.mdb") as connection:
            connection.cursor().execute("SELECT")
        self.assertEqual(self.connect.counts.connections_opened, 1)
        manager.close()
        self.assert_all_resources_released()

    def test_result_parsing_exception_releases_cursor_and_keeps_healthy_cache(self):
        manager = MdbConnectionManager()
        with self.assertRaisesRegex(ValueError, "parse failed"):
            with manager.connection("parse-error.mdb") as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT").fetchall()
                    raise ValueError("parse failed")
        self.assert_cursors_released()
        self.assertEqual(self.connect.counts.active_connections, 1)
        manager.close()
        self.assert_all_resources_released()

    def test_early_return_releases_cursor(self):
        manager = MdbConnectionManager()

        def read_first_row():
            with manager.connection("early-return.mdb") as connection:
                with connection.cursor() as cursor:
                    return cursor.execute("SELECT").fetchall()[0]

        self.assertEqual(read_first_row(), ("row",))
        self.assert_cursors_released()
        manager.close()
        self.assert_all_resources_released()

    def test_repeated_reads_reuse_one_cached_connection_without_cursor_growth(self):
        manager = MdbConnectionManager()
        for _index in range(500):
            with manager.connection("repeated.mdb") as connection:
                connection.cursor().execute("SELECT")
        self.assertEqual(self.connect.counts.connections_opened, 1)
        self.assertEqual(len(manager._read_conns), 1)
        self.assert_cursors_released()
        manager.close()
        self.assert_all_resources_released()

    def test_windows_path_case_variants_share_one_connection_identity(self):
        manager = MdbConnectionManager()
        with manager.connection("Case-Variant.mdb") as first:
            first_connection = first._conn
        with manager.connection("case-variant.mdb") as second:
            self.assertIs(second._conn, first_connection)
        self.assertEqual(self.connect.counts.connections_opened, 1)
        manager.close_database("CASE-VARIANT.MDB")
        self.assert_all_resources_released()

    def test_cursor_context_closes_before_outer_read_lease_exits(self):
        manager = MdbConnectionManager()
        with manager.connection("cursor-scope.mdb") as connection:
            for _index in range(500):
                with connection.cursor() as cursor:
                    cursor.execute("SELECT").fetchall()
                self.assertEqual(self.connect.counts.active_cursors, 0)
        self.assertEqual(self.connect.counts.max_active_cursors, 1)
        manager.close()
        self.assert_all_resources_released()

    def test_repeated_inner_queries_do_not_exhaust_access_table_handles(self):
        self.connect.max_active_cursors = 4
        manager = MdbConnectionManager()
        with manager.connection("table-handles.mdb") as connection:
            for _index in range(500):
                with connection.cursor() as cursor:
                    cursor.execute("SELECT").fetchall()
        self.assertEqual(self.connect.counts.max_active_cursors, 1)
        manager.close()
        self.assert_all_resources_released()

    def test_cursor_connection_uses_managed_connection_wrapper(self):
        manager = MdbConnectionManager()
        with manager.connection("schema-cursor.mdb") as connection:
            with connection.cursor() as cursor:
                with cursor.connection.cursor() as schema_cursor:
                    schema_cursor.execute("SELECT").fetchall()
                self.assertEqual(self.connect.counts.active_cursors, 1)
            self.assertEqual(self.connect.counts.active_cursors, 0)
        manager.close()
        self.assert_all_resources_released()

    def test_nested_read_leases_reuse_connection_without_closing_outer_cursor(self):
        manager = MdbConnectionManager()
        with manager.connection("nested.mdb") as outer:
            outer_cursor = outer.cursor()
            with manager.connection("nested.mdb") as inner:
                self.assertIs(outer._conn, inner._conn)
                inner.cursor().execute("SELECT")
            self.assertFalse(outer_cursor._closed)
        self.assert_cursors_released()
        manager.close()
        self.assert_all_resources_released()

    def test_nested_mixed_mode_lease_is_rejected_without_closing_outer_lease(self):
        manager = MdbConnectionManager()
        with manager.connection("nested-mode.mdb") as outer:
            with self.assertRaisesRegex(RuntimeError, "same mode"):
                with manager.connection("nested-mode.mdb", autocommit=False):
                    pass
            outer.cursor().execute("SELECT")
        self.assert_cursors_released()
        manager.close()
        self.assert_all_resources_released()

    def test_worker_thread_releases_lease_cursors_without_thread_local_cache(self):
        manager = MdbConnectionManager()
        worker_thread_ids = []

        def work() -> None:
            with manager.connection("worker.mdb") as connection:
                worker_thread_ids.append(threading.get_ident())
                connection.cursor().execute("SELECT")

        worker = threading.Thread(target=work)
        worker.start()
        worker.join()
        self.assertEqual(len(worker_thread_ids), 1)
        self.assert_cursors_released()
        self.assertNotIn("_thread_connections", vars(manager))
        manager.close()
        self.assert_all_resources_released()

    def test_same_database_worker_leases_are_serialized(self):
        manager = MdbConnectionManager()
        first_entered = threading.Event()
        release_first = threading.Event()
        second_attempting = threading.Event()
        second_entered = threading.Event()

        def first_work() -> None:
            with manager.connection("shared.mdb"):
                first_entered.set()
                release_first.wait(timeout=2.0)

        def second_work() -> None:
            second_attempting.set()
            with manager.connection("shared.mdb"):
                second_entered.set()

        first = threading.Thread(target=first_work)
        second = threading.Thread(target=second_work)
        first.start()
        self.assertTrue(first_entered.wait(timeout=2.0))
        second.start()
        self.assertTrue(second_attempting.wait(timeout=2.0))
        self.assertFalse(second_entered.wait(timeout=0.05))
        release_first.set()
        first.join()
        second.join()
        self.assertTrue(second_entered.is_set())
        self.assertEqual(self.connect.counts.connections_opened, 1)
        manager.close()
        self.assert_all_resources_released()

    def test_database_close_releases_only_requested_database(self):
        manager = MdbConnectionManager()
        with manager.connection("old.mdb"):
            pass
        with manager.connection("new.mdb"):
            pass
        manager.close_database("old.mdb")
        self.assertEqual(self.connect.counts.active_connections, 1)
        self.assertEqual(len(manager._read_conns), 1)
        manager.close()
        self.assert_all_resources_released()

    def test_database_close_releases_read_and_write_connections_for_path(self):
        manager = MdbConnectionManager()
        with manager.connection("old.mdb"):
            pass
        with manager.connection("old.mdb", autocommit=False):
            pass
        with manager.connection("new.mdb"):
            pass
        manager.close_database("old.mdb")
        self.assertEqual(self.connect.counts.active_connections, 1)
        self.assertNotIn("old.mdb", " ".join(manager._read_conns))
        self.assertNotIn("old.mdb", " ".join(manager._write_conns))
        manager.close()
        self.assert_all_resources_released()

    def test_multiple_databases_isolate_failed_writer_recovery(self):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        for path in ("first.mdb", "second.mdb"):
            with manager.connection(path):
                pass
            with writer._connection(path):
                pass
        second_key = os.path.normcase(os.path.abspath("second.mdb"))
        second_read = manager._read_conns[second_key]
        second_write = manager._write_conns[second_key]
        with self.assertRaisesRegex(pyodbc.OperationalError, "connection failed"):
            with writer._connection("first.mdb") as connection:
                connection.cursor().execute("RAISE_QUERY_ERROR")
        self.assertIs(manager._read_conns[second_key], second_read)
        self.assertIs(
            manager._write_conns[second_key],
            second_write,
        )
        with writer._connection("first.mdb"):
            pass
        self.assertEqual(self.connect.counts.connections_opened, 5)
        manager.close()
        self.assert_all_resources_released()

    def test_failed_writer_does_not_poison_reader_for_same_database(self):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        path = "split-handles.mdb"
        path_key = os.path.normcase(os.path.abspath(path))
        with manager.connection(path):
            pass
        original_reader = manager._read_conns[path_key]
        with self.assertRaisesRegex(pyodbc.OperationalError, "connection failed"):
            with writer._connection(path) as connection:
                connection.cursor().execute("RAISE_QUERY_ERROR")
        with manager.connection(path) as connection:
            self.assertIs(connection._conn, original_reader)
        with writer._connection(path):
            pass
        self.assertEqual(self.connect.counts.connections_opened, 3)
        manager.close()
        self.assert_all_resources_released()

    def test_failed_reader_does_not_poison_writer_for_same_database(self):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        path = "split-handles.mdb"
        path_key = os.path.normcase(os.path.abspath(path))
        with manager.connection(path):
            pass
        with manager.connection(path, autocommit=False):
            pass
        original_writer = manager._write_conns[path_key]
        with self.assertRaisesRegex(pyodbc.OperationalError, "connection failed"):
            with manager.connection(path) as connection:
                connection.cursor().execute("RAISE_QUERY_ERROR")
        with writer._connection(path) as connection:
            self.assertIs(connection._conn, original_writer)
        self.assertEqual(self.connect.counts.connections_opened, 2)
        manager.close()
        self.assert_all_resources_released()

    def test_maintenance_closes_reused_handles_and_reopens_fresh_incarnation(self):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        path = "maintenance-reuse.mdb"
        with manager.connection(path):
            pass
        for _index in range(100):
            with writer._connection(path):
                pass
        path_key = os.path.normcase(os.path.abspath(path))
        old_read = manager._read_conns[path_key]
        old_write = manager._write_conns[path_key]
        with manager.maintenance(path):
            self.assertTrue(old_read.closed)
            self.assertTrue(old_write.closed)
            self.assertEqual(self.connect.counts.active_connections, 0)
            with self.assertRaisesRegex(RuntimeError, "temporarily closed"):
                with manager.connection(path):
                    pass
        with manager.connection(path):
            pass
        with writer._connection(path):
            pass
        self.assertEqual(self.connect.counts.connections_opened, 4)
        manager.close()
        self.assert_all_resources_released()

    def test_database_close_failure_retains_connection_for_retry(self):
        manager = MdbConnectionManager()
        with manager.connection("retry-close.mdb"):
            pass
        abs_path = next(iter(manager._read_conns))
        connection = manager._read_conns[abs_path]
        original_close = connection.close
        close_attempts = []

        def fail_once():
            close_attempts.append(True)
            if len(close_attempts) == 1:
                raise pyodbc.OperationalError("close failed")
            original_close()

        connection.close = fail_once
        with self.assertRaisesRegex(pyodbc.OperationalError, "close failed"):
            manager.close_database("retry-close.mdb")
        self.assertIs(manager._read_conns[abs_path], connection)
        self.assertFalse(connection.closed)
        manager.close_database("retry-close.mdb")
        self.assertNotIn(abs_path, manager._read_conns)
        self.assertTrue(connection.closed)
        self.assertEqual(len(close_attempts), 2)
        self.assert_all_resources_released()

    def test_reader_refresh_reopens_write_handle_for_same_path_replacement(self):
        manager = MdbConnectionManager()
        reader = MdbReader(conn_manager=manager)
        writer = MdbWriter(conn_manager=manager)
        with writer._connection("replacement.mdb"):
            pass
        original_write_connection = manager._write_conns[
            next(iter(manager._write_conns))
        ]
        reader.refresh_connection("replacement.mdb")
        self.assertTrue(original_write_connection.closed)
        self.assertEqual(manager._write_conns, {})
        with writer._connection("replacement.mdb"):
            pass
        replacement_write_connection = manager._write_conns[
            next(iter(manager._write_conns))
        ]
        self.assertIsNot(replacement_write_connection, original_write_connection)
        manager.close()
        self.assert_all_resources_released()

    def test_routed_reader_refresh_reopens_write_handle_for_same_path_replacement(self):
        manager = MdbConnectionManager()
        reader = DatabaseProjectReader(
            manager,
            DatabaseDescriptorRegistry(),
            object(),
        )
        writer = MdbWriter(conn_manager=manager)
        with writer._connection("routed-replacement.mdb"):
            pass
        original_write_connection = manager._write_conns[
            next(iter(manager._write_conns))
        ]
        reader.refresh_connection("routed-replacement.mdb")
        self.assertTrue(original_write_connection.closed)
        self.assertEqual(manager._write_conns, {})
        with writer._connection("routed-replacement.mdb"):
            pass
        replacement_write_connection = manager._write_conns[
            next(iter(manager._write_conns))
        ]
        self.assertIsNot(replacement_write_connection, original_write_connection)
        manager.close()
        self.assert_all_resources_released()

    def test_shutdown_closes_all_cached_read_and_write_connections(self):
        manager = MdbConnectionManager()
        with manager.connection("read.mdb"):
            pass
        with manager.connection("write.mdb", autocommit=False):
            pass
        manager.close()
        self.assert_all_resources_released()

    def test_shutdown_closes_connection_and_cursors_from_active_lease(self):
        manager = MdbConnectionManager()
        lease = manager.connection("active.mdb")
        connection = lease.__enter__()
        connection.cursor().execute("SELECT")
        manager.close()
        lease.__exit__(None, None, None)
        self.assert_all_resources_released()

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

    def test_client_task_exhaustion_is_classified_without_retry(self):
        self.connect.max_opens = 0
        manager = MdbConnectionManager()
        with self.assertRaisesRegex(
            DatabaseConnectionUnavailableError,
            "restart OST Visualizer",
        ):
            with manager.connection("exhausted.mdb", autocommit=False):
                pass
        self.assertEqual(self.connect.connect_attempts, 1)
        self.assertEqual(self.connect.counts.connections_opened, 0)
        self.assertEqual(manager._read_conns, {})
        self.assertEqual(manager._write_conns, {})

    def test_exhaustion_on_another_database_keeps_cached_database_usable(self):
        manager = MdbConnectionManager()
        with manager.connection("usable.mdb"):
            pass
        self.connect.max_opens = 1
        with self.assertRaises(DatabaseConnectionUnavailableError):
            with manager.connection("exhausted.mdb"):
                pass
        with manager.connection("usable.mdb"):
            pass
        self.assertEqual(self.connect.connect_attempts, 2)
        self.assertEqual(self.connect.counts.connections_opened, 1)
        manager.close()
        self.assert_all_resources_released()

    def test_mutation_service_returns_failed_result_for_connection_exhaustion(self):
        message = "Restart OST Visualizer and try again."
        executor = _UnavailableMutationExecutor(message)
        concurrency = _MutationScope()
        service = DatabaseMutationWriteService(
            reload_database=lambda _database_id: True,
            event_bus=type(
                "EventBus", (), {"publish": lambda *_args, **_kwargs: None}
            )(),
            mutation_executor=executor,
            session_registry=type(
                "SessionRegistry",
                (),
                {
                    "get": lambda _self, _database_id: None,
                    "lock_tokens": lambda _self, _database_id, _resources: (),
                },
            )(),
            concurrency_tokens=concurrency,
            database_capability_service=type(
                "Capability",
                (),
                {"is_editable": lambda _self, _database_id, _resource=None: True},
            )(),
        )
        result = service._execute_database_mutation(
            "exhausted.mdb",
            (ResourceRef("takeoffs_collection", "7", 7),),
            lambda _recorder: ["99"],
            operation_id=str(uuid.uuid4()),
        )
        self.assertEqual(
            result.outcome_status,
            MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
        )
        self.assertEqual(result.failure_reason, message)
        self.assertFalse(result.commit_attempted)
        self.assertEqual(executor.calls, 1)
        self.assertEqual(concurrency.applied, [])

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


if __name__ == "__main__":
    unittest.main()
