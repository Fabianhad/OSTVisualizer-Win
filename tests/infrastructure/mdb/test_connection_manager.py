import asyncio
import os
import sys
import threading
import unittest
from typing import Optional
from unittest.mock import patch
import pyodbc
from ost_visualizer.application.interfaces.i_mdb_connection_manager import (
    DatabaseConnectionUnavailableError,
)
from ost_visualizer.infrastructure.database.connection_wrapper import ConnectionWrapper
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.reader_router import DatabaseProjectReader
from ost_visualizer.infrastructure.mdb.connection_manager import (
    MdbConnectionManager,
    WriteBlockedError,
)
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _Abort(BaseException):
    # A BaseException that is neither KeyboardInterrupt nor SystemExit.
    pass


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
        if sql == "RAISE_DEAD_CONNECTION_STATEMENT_ERROR":
            # A non-connection-class SQLSTATE although the handle is gone: only
            # the health probe can tell.
            self._connection.unhealthy = True
            raise pyodbc.OperationalError("HY000", "statement failed")
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
        # A rollback that fails WITHOUT a connection-class SQLSTATE and leaves
        # the health probe passing: the pending statements stay uncommitted.
        self.rollback_error = None
        # One transient cursor failure: the next health probe fails, a later
        # one passes again (the handle is flaky, not dead).
        self.fail_cursor_open_once = False
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
        if self.fail_cursor_open_once:
            self.fail_cursor_open_once = False
            raise pyodbc.OperationalError("HY000", "cursor could not be opened")
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
        if self.rollback_error is not None:
            error, self.rollback_error = self.rollback_error, None
            raise error
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

    def test_failed_close_after_connection_error_is_attempted_once_per_release(self):
        manager = MdbConnectionManager()
        close_attempts = []
        with self.assertRaisesRegex(pyodbc.OperationalError, "communication link"):
            with manager.connection("double-close.mdb") as connection:
                first_connection = connection._conn
                original_close = first_connection.close

                def fail_close_once():
                    close_attempts.append(True)
                    if len(close_attempts) == 1:
                        raise pyodbc.OperationalError(
                            "HY000", "connection close failed"
                        )
                    original_close()

                first_connection.close = fail_close_once
                first_connection.fail_next_cursor_close = True
                connection.cursor().execute("RAISE_CONNECTION_CLASS_ERROR")
        # One release: one close attempt, even though both the connection
        # error and the cursor-cleanup failure ask for the handle to go.
        self.assertEqual(len(close_attempts), 1)
        self.assertFalse(first_connection.closed)
        self.assertIn(id(first_connection), manager._unhealthy_connection_ids)
        self.assertIs(
            manager._read_conns[os.path.normcase(os.path.abspath("double-close.mdb"))],
            first_connection,
        )
        # The failed close stays owned and is retried on the NEXT lease.
        with manager.connection("double-close.mdb") as connection:
            self.assertIsNot(connection._conn, first_connection)
        self.assertEqual(len(close_attempts), 2)
        self.assertTrue(first_connection.closed)
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
        contended = _ContendedRLock()
        manager._path_locks[os.path.normcase(os.path.abspath("shared.mdb"))] = contended
        first_entered = threading.Event()
        release_first = threading.Event()
        second_attempting = threading.Event()
        second_entered = threading.Event()
        first_released_when_second_entered = []

        def first_work() -> None:
            with manager.connection("shared.mdb"):
                first_entered.set()
                release_first.wait(timeout=2.0)

        def second_work() -> None:
            second_attempting.set()
            with manager.connection("shared.mdb"):
                first_released_when_second_entered.append(release_first.is_set())
                second_entered.set()

        first = threading.Thread(target=first_work)
        second = threading.Thread(target=second_work)
        first.start()
        self.assertTrue(first_entered.wait(timeout=2.0))
        second.start()
        self.assertTrue(second_attempting.wait(timeout=2.0))
        # The second worker found the database lock held and is blocked on it.
        self.assertTrue(contended.contended.wait(timeout=2.0))
        self.assertFalse(second_entered.is_set())
        release_first.set()
        first.join()
        second.join()
        self.assertTrue(second_entered.is_set())
        self.assertEqual(first_released_when_second_entered, [True])
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

    def test_other_connect_errors_propagate_unclassified_and_cache_nothing(self):
        failures = (
            pyodbc.OperationalError("08004", "connection rejected by server"),
            pyodbc.OperationalError("HY000", "too few client tasks (-1036)"),
            pyodbc.Error("HY000", "driver failure"),
        )
        for failure in failures:
            with self.subTest(failure=failure.args):
                with patch(
                    "ost_visualizer.infrastructure.mdb.connection_manager."
                    "pyodbc.connect",
                    side_effect=failure,
                ):
                    manager = MdbConnectionManager()
                    with self.assertRaises(pyodbc.Error) as raised:
                        with manager.connection("failing.mdb"):
                            self.fail("connection lease granted")
                self.assertIs(raised.exception, failure)
                self.assertNotIsInstance(
                    raised.exception, DatabaseConnectionUnavailableError
                )
                self.assertEqual(manager._read_conns, {})
                self.assertEqual(manager._active_leases, {})

    def test_write_block_rejects_writer_leases_and_closes_cached_writers_only(self):
        manager = MdbConnectionManager()
        with manager.connection("blocked.mdb"):
            pass
        with manager.connection("blocked.mdb", autocommit=False):
            pass
        reader = manager._read_conns[os.path.normcase(os.path.abspath("blocked.mdb"))]
        writer = manager._write_conns[os.path.normcase(os.path.abspath("blocked.mdb"))]
        manager.set_write_blocked(True)
        self.assertTrue(manager.is_write_blocked())
        self.assertTrue(writer.closed)
        self.assertFalse(reader.closed)
        self.assertEqual(manager._write_conns, {})
        with self.assertRaises(WriteBlockedError):
            with manager.connection("blocked.mdb", autocommit=False):
                self.fail("writer lease granted while writes are blocked")
        self.assertEqual(manager._active_leases, {})
        with manager.connection("blocked.mdb") as connection:
            self.assertIs(connection._conn, reader)
        manager.set_write_blocked(False)
        self.assertFalse(manager.is_write_blocked())
        with manager.connection("blocked.mdb", autocommit=False) as connection:
            self.assertIsNot(connection._conn, writer)
        self.assertEqual(self.connect.counts.connections_opened, 3)
        manager.close()
        self.assert_all_resources_released()

    def test_close_attempts_every_connection_and_reports_all_failures(self):
        manager = MdbConnectionManager()
        for path in ("first.mdb", "second.mdb", "third.mdb"):
            with manager.connection(path):
                pass
        connections = {
            key: connection for key, connection in manager._read_conns.items()
        }
        failing_keys = [key for key in connections if not key.endswith("third.mdb")]
        for key in failing_keys:
            connections[key].fail_close = True
            original_close = connections[key].close

            def failing_close(connection=connections[key], close=original_close):
                if connection.fail_close:
                    raise pyodbc.OperationalError("HY000", "close failed")
                close()

            connections[key].close = failing_close
        with self.assertRaises(ExceptionGroup) as raised:
            manager.close()
        self.assertEqual(len(raised.exception.exceptions), 2)
        self.assertEqual(self.connect.counts.active_connections, 2)
        self.assertEqual(sorted(manager._read_conns), sorted(failing_keys))
        for key in failing_keys:
            connections[key].fail_close = False
        manager.close()
        self.assert_all_resources_released()

    def test_committed_writer_read_preference_is_ignored_during_active_leases(self):
        manager = MdbConnectionManager()
        path_key = os.path.normcase(os.path.abspath("preference.mdb"))
        with manager.connection("preference.mdb"):
            manager.use_committed_writer_for_reads("preference.mdb")
            self.assertNotIn(path_key, manager._writer_read_paths)
        manager.use_committed_writer_for_reads("preference.mdb")
        self.assertIn(path_key, manager._writer_read_paths)
        manager.close_database("preference.mdb")
        self.assertNotIn(path_key, manager._writer_read_paths)
        manager.close()
        self.assert_all_resources_released()

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


class ConnectionMaintenanceExclusionTests(unittest.TestCase):
    def test_connection_manager_excludes_leases_and_closes_both_pools(self):
        manager = MdbConnectionManager()
        path = os.path.normcase(os.path.abspath("sample.mdb"))
        read, write = Mock(), Mock()
        manager._read_conns[path] = read
        manager._write_conns[path] = write
        with manager.maintenance(path):
            read.close.assert_called_once()
            write.close.assert_called_once()
            for mode in (True, False):
                with self.assertRaisesRegex(RuntimeError, "maintenance"):
                    with manager.connection(path.upper(), autocommit=mode):
                        self.fail("lease granted during maintenance")
            with self.assertRaisesRegex(RuntimeError, "active operations"):
                with manager.maintenance(path):
                    self.fail("overlapping maintenance")
        self.assertFalse(manager._maintenance_paths)
        self.assertFalse(manager._read_conns)
        self.assertFalse(manager._write_conns)

    def test_active_lease_and_failed_close_prevent_maintenance(self):
        manager = MdbConnectionManager()
        path = os.path.normcase(os.path.abspath("sample.mdb"))
        with patch(
            "ost_visualizer.infrastructure.mdb.connection_manager.pyodbc.connect",
            return_value=Mock(),
        ):
            with manager.connection(path):
                with self.assertRaisesRegex(RuntimeError, "active operations"):
                    with manager.maintenance(path):
                        self.fail("active lease compacted")
        conn = manager._read_conns[path]
        conn.close.side_effect = pyodbc.Error("close failed")
        with self.assertRaisesRegex(pyodbc.Error, "close failed"):
            with manager.maintenance(path):
                self.fail("failed close permitted maintenance")
        conn.close.assert_called_once_with()
        self.assertIs(manager._read_conns[path], conn)
        self.assertFalse(manager._maintenance_paths)
        self.assertEqual(manager._active_leases, {})


class MdbConnectionManagerHandleHealthTests(unittest.TestCase):
    """Second-pass coverage: handle health, lease nesting and path identity."""

    def setUp(self) -> None:
        self.connect = _FakeConnect()
        self.connect_patch = patch(
            "ost_visualizer.infrastructure.mdb.connection_manager.pyodbc.connect",
            self.connect,
        )
        self.connect_patch.start()

    def tearDown(self) -> None:
        self.connect_patch.stop()

    def assert_all_resources_released(self) -> None:
        counts = self.connect.counts
        self.assertEqual(counts.connections_opened, counts.connections_closed)
        self.assertEqual(counts.active_connections, 0)
        self.assertEqual(counts.cursors_created, counts.cursors_closed)

    def test_failed_rollback_evicts_writer_even_when_the_health_probe_passes(self):
        # AGENTS.md: a failed rollback marks that physical handle unhealthy. A
        # non-08 SQLSTATE leaves the probe passing, so only the rollback failure
        # itself can condemn the handle; otherwise its uncommitted statements
        # would ride along with the next mutation's commit.
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        with writer._connection("rollback-hy000.mdb") as connection:
            first_connection = connection._conn
        failure = pyodbc.OperationalError("HY000", "rollback refused")
        first_connection.rollback_error = failure
        with self.assertRaises(pyodbc.OperationalError) as raised:
            with writer._connection("rollback-hy000.mdb") as connection:
                connection.cursor().execute("INSERT_PENDING")
                raise ValueError("validation failed after statement")
        self.assertIs(raised.exception, failure)
        self.assertEqual(self.connect.counts.rollbacks, 1)
        with writer._connection("rollback-hy000.mdb") as connection:
            self.assertIsNot(connection._conn, first_connection)
            visible = connection.cursor().execute("SELECT_VISIBLE_ROWS").fetchall()
            self.assertEqual(visible, [])
        self.assertTrue(first_connection.closed)
        self.assertEqual(self.connect.counts.connections_opened, 2)
        self.assertEqual(self.connect.counts.committed_rows, [])
        manager.close()
        self.assert_all_resources_released()

    def test_failed_rollback_of_a_borrowed_writer_read_lease_evicts_only_that_handle(
        self,
    ):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        path = "borrowed-rollback.mdb"
        path_key = os.path.normcase(os.path.abspath(path))
        with manager.connection(path):
            pass
        reader_connection = manager._read_conns[path_key]
        with writer._connection(path):
            pass
        writer_connection = manager._write_conns[path_key]
        failure = pyodbc.OperationalError("HY000", "rollback refused")
        with self.assertRaises(pyodbc.OperationalError) as raised:
            with manager.connection(path) as connection:
                self.assertIs(connection._conn, writer_connection)
                writer_connection.rollback_error = failure
        self.assertIs(raised.exception, failure)
        self.assertTrue(writer_connection.closed)
        self.assertEqual(manager._write_conns, {})
        self.assertFalse(reader_connection.closed)
        self.assertIs(manager._read_conns[path_key], reader_connection)
        with writer._connection(path) as connection:
            self.assertIsNot(connection._conn, writer_connection)
        manager.close()
        self.assert_all_resources_released()

    def test_an_interrupted_write_is_not_committed_by_the_next_transaction(self):
        # Interrupt policy: the pooled write connection is not autocommit, so an
        # interrupt (KeyboardInterrupt/SystemExit) must roll the transaction
        # back; otherwise the next commit on the reused handle commits it.
        for interrupt_type in (KeyboardInterrupt, SystemExit):
            with self.subTest(interrupt=interrupt_type.__name__):
                manager = MdbConnectionManager()
                writer = MdbWriter(conn_manager=manager)
                path = f"interrupted-{interrupt_type.__name__}.mdb"
                counts = self.connect.counts
                committed_before = len(counts.committed_rows)
                rollbacks_before = counts.rollbacks
                interrupt = interrupt_type()
                with self.assertRaises(interrupt_type) as raised:
                    with writer._connection(path) as connection:
                        connection.cursor().execute("INSERT_PENDING")
                        raise interrupt
                self.assertIs(raised.exception, interrupt)
                self.assertEqual(counts.rollbacks, rollbacks_before + 1)
                with writer._connection(path) as connection:
                    connection.cursor().execute("INSERT_PENDING")
                self.assertEqual(len(counts.committed_rows), committed_before + 1)
                manager.close()
        self.assert_all_resources_released()

    def test_a_failed_rollback_during_an_interrupt_is_logged_and_evicts_the_handle(
        self,
    ):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        path = "interrupt-rollback-hy000.mdb"
        with writer._connection(path) as connection:
            first_connection = connection._conn
        failure = pyodbc.OperationalError("HY000", "rollback refused")
        first_connection.rollback_error = failure
        interrupt = KeyboardInterrupt()
        with self.assertLogs(writer.logger, level="ERROR") as logged:
            with self.assertRaises(KeyboardInterrupt) as raised:
                with writer._connection(path) as connection:
                    connection.cursor().execute("INSERT_PENDING")
                    raise interrupt
        self.assertIs(raised.exception, interrupt)
        self.assertIn("KeyboardInterrupt", logged.records[0].getMessage())
        self.assertIs(logged.records[0].exc_info[1], failure)
        self.assertTrue(first_connection.closed)
        with writer._connection(path) as connection:
            self.assertIsNot(connection._conn, first_connection)
            visible = connection.cursor().execute("SELECT_VISIBLE_ROWS").fetchall()
            self.assertEqual(visible, [])
        self.assertEqual(self.connect.counts.committed_rows, [])
        manager.close()
        self.assert_all_resources_released()

    def test_an_interrupt_in_a_borrowed_writer_read_lease_is_not_masked_by_a_failed_rollback(
        self,
    ):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        path = "borrowed-interrupt.mdb"
        path_key = os.path.normcase(os.path.abspath(path))
        with manager.connection(path):
            pass
        reader_connection = manager._read_conns[path_key]
        with writer._connection(path):
            pass
        writer_connection = manager._write_conns[path_key]
        failure = pyodbc.OperationalError("HY000", "rollback refused")
        interrupt = KeyboardInterrupt()
        with self.assertLogs(_MANAGER_MODULE, level="ERROR") as logged:
            with self.assertRaises(KeyboardInterrupt) as raised:
                with manager.connection(path) as connection:
                    self.assertIs(connection._conn, writer_connection)
                    writer_connection.rollback_error = failure
                    raise interrupt
        self.assertIs(raised.exception, interrupt)
        self.assertEqual(len(logged.records), 1)
        self.assertEqual(
            logged.records[0].getMessage(),
            "The MDB read lease on the writer connection could not be rolled "
            "back after KeyboardInterrupt.",
        )
        self.assertIs(logged.records[0].exc_info[1], failure)
        self.assertTrue(writer_connection.closed)
        self.assertEqual(manager._write_conns, {})
        self.assertFalse(reader_connection.closed)
        self.assertIs(manager._read_conns[path_key], reader_connection)
        self.assertEqual(manager._active_leases, {})
        manager.close()
        self.assert_all_resources_released()

    def test_a_second_interrupt_from_the_borrowed_lease_rollback_is_not_swallowed(self):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        path = "borrowed-second-interrupt.mdb"
        path_key = os.path.normcase(os.path.abspath(path))
        with writer._connection(path):
            pass
        writer_connection = manager._write_conns[path_key]
        second = SystemExit(2)
        first = KeyboardInterrupt()
        with self.assertRaises(SystemExit) as raised:
            with manager.connection(path):
                writer_connection.rollback_error = second
                raise first
        self.assertIs(raised.exception, second)
        self.assertIs(raised.exception.__context__, first)
        self.assertEqual(manager._active_leases, {})
        manager.close()
        self.assert_all_resources_released()

    def _warm_writer_handle(self, writer, path):
        with writer._connection(path) as connection:
            return connection._conn

    def _committed_by_next_write(self, writer, path):
        before = len(self.connect.counts.committed_rows)
        with writer._connection(path) as connection:
            connection.cursor().execute("INSERT_PENDING")
        return len(self.connect.counts.committed_rows) - before

    def test_an_interrupt_raised_by_the_rollback_itself_evicts_the_handle(self):
        # The rollback was interrupted: its outcome is unknown, so the pending
        # statements must not survive on the pooled non-autocommit handle.
        for first, second in (
            (KeyboardInterrupt(), SystemExit(2)),
            (SystemExit(1), KeyboardInterrupt()),
            (_Abort(), KeyboardInterrupt()),
        ):
            with self.subTest(first=type(first).__name__, second=type(second).__name__):
                manager = MdbConnectionManager()
                writer = MdbWriter(conn_manager=manager)
                path = f"rollback-interrupted-{type(first).__name__}.mdb"
                handle = self._warm_writer_handle(writer, path)
                handle.rollback_error = second
                with self.assertRaises(type(second)) as raised:
                    with writer._connection(path) as connection:
                        connection.cursor().execute("INSERT_PENDING")
                        raise first
                self.assertIs(raised.exception, second)
                self.assertTrue(handle.closed)
                self.assertEqual(self._committed_by_next_write(writer, path), 1)
                manager.close()
        self.assert_all_resources_released()

    def test_an_interrupt_raised_by_the_rollback_of_an_ordinary_failure_evicts_the_handle(
        self,
    ):
        for interrupt_type in (KeyboardInterrupt, SystemExit, _Abort):
            with self.subTest(interrupt=interrupt_type.__name__):
                manager = MdbConnectionManager()
                writer = MdbWriter(conn_manager=manager)
                path = f"ordinary-rollback-{interrupt_type.__name__}.mdb"
                handle = self._warm_writer_handle(writer, path)
                interrupt = interrupt_type()
                handle.rollback_error = interrupt
                with self.assertRaises(interrupt_type) as raised:
                    with writer._connection(path) as connection:
                        connection.cursor().execute("INSERT_PENDING")
                        raise ValueError("validation failed")
                self.assertIs(raised.exception, interrupt)
                self.assertTrue(handle.closed)
                self.assertEqual(self._committed_by_next_write(writer, path), 1)
                manager.close()
        self.assert_all_resources_released()

    def test_a_failed_rollback_after_any_baseexception_evicts_the_handle(self):
        for exception_type in (
            KeyboardInterrupt,
            SystemExit,
            _Abort,
            asyncio.CancelledError,
        ):
            with self.subTest(exception=exception_type.__name__):
                manager = MdbConnectionManager()
                writer = MdbWriter(conn_manager=manager)
                path = f"baseexception-{exception_type.__name__}.mdb"
                handle = self._warm_writer_handle(writer, path)
                failure = pyodbc.OperationalError("HY000", "rollback refused")
                handle.rollback_error = failure
                abort = exception_type()
                with self.assertLogs(writer.logger, level="ERROR") as logged:
                    with self.assertRaises(exception_type) as raised:
                        with writer._connection(path) as connection:
                            connection.cursor().execute("INSERT_PENDING")
                            raise abort
                self.assertIs(raised.exception, abort)
                self.assertEqual(
                    logged.records[0].getMessage(),
                    "The MDB transaction could not be rolled back after "
                    f"{exception_type.__name__}.",
                )
                self.assertTrue(handle.closed)
                self.assertEqual(self._committed_by_next_write(writer, path), 1)
                manager.close()
        self.assert_all_resources_released()

    def test_a_borrowed_read_lease_rollback_error_never_replaces_a_baseexception(self):
        for exception_type in (KeyboardInterrupt, SystemExit, _Abort):
            for failure in (
                pyodbc.OperationalError("HY000", "rollback refused"),
                RuntimeError("driver bug"),
            ):
                with self.subTest(
                    exception=exception_type.__name__, failure=type(failure).__name__
                ):
                    manager = MdbConnectionManager()
                    writer = MdbWriter(conn_manager=manager)
                    path = (
                        f"lease-{exception_type.__name__}-{type(failure).__name__}.mdb"
                    )
                    path_key = os.path.normcase(os.path.abspath(path))
                    with writer._connection(path):
                        pass
                    writer_connection = manager._write_conns[path_key]
                    abort = exception_type()
                    with self.assertLogs(_MANAGER_MODULE, level="ERROR") as logged:
                        with self.assertRaises(exception_type) as raised:
                            with manager.connection(path) as connection:
                                self.assertIs(connection._conn, writer_connection)
                                writer_connection.rollback_error = failure
                                raise abort
                    self.assertIs(raised.exception, abort)
                    self.assertEqual(len(logged.records), 1)
                    self.assertEqual(
                        logged.records[0].getMessage(),
                        "The MDB read lease on the writer connection could not be "
                        f"rolled back after {exception_type.__name__}.",
                    )
                    self.assertIs(logged.records[0].exc_info[1], failure)
                    self.assertEqual(manager._active_leases, {})
                    if isinstance(failure, pyodbc.Error):
                        self.assertTrue(writer_connection.closed)
                        self.assertEqual(manager._write_conns, {})
                    manager.close()
        self.assert_all_resources_released()

    def test_an_ordinary_error_from_the_borrowed_read_lease_rollback_still_propagates(
        self,
    ):
        # Control: without an interrupt in flight the guard re-raises (old behaviour).
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        path = "lease-ordinary.mdb"
        path_key = os.path.normcase(os.path.abspath(path))
        with writer._connection(path):
            pass
        writer_connection = manager._write_conns[path_key]
        failure = RuntimeError("driver bug")
        with self.assertRaises(RuntimeError) as raised:
            with manager.connection(path):
                writer_connection.rollback_error = failure
        self.assertIs(raised.exception, failure)
        self.assertEqual(manager._active_leases, {})
        manager.close()
        self.assert_all_resources_released()

    def test_an_interrupt_alone_does_not_evict_a_handle_that_is_not_known_broken(self):
        # An interrupt is not evidence of a dead handle: the health probe runs only
        # for driver errors, and a dead handle is replaced by the next lease entry.
        for interrupt_type in (KeyboardInterrupt, SystemExit):
            with self.subTest(interrupt=interrupt_type.__name__):
                manager = MdbConnectionManager()
                writer = MdbWriter(conn_manager=manager)
                path = f"dead-{interrupt_type.__name__}.mdb"
                handle = self._warm_writer_handle(writer, path)
                with self.assertRaises(interrupt_type):
                    with manager.connection(path, autocommit=False):
                        handle.unhealthy = True
                        raise interrupt_type()
                self.assertFalse(handle.closed)
                with writer._connection(path) as connection:
                    self.assertIsNot(connection._conn, handle)
                self.assertTrue(handle.closed)
                manager.close()
        self.assert_all_resources_released()

    def test_an_ordinary_error_is_still_replaced_by_a_failed_borrowed_lease_rollback(
        self,
    ):
        # Control for the interrupt guard: with an ordinary Exception in flight the
        # driver rollback error still replaces it (old behaviour) and is not logged.
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        path = "lease-ordinary-replaced.mdb"
        path_key = os.path.normcase(os.path.abspath(path))
        with writer._connection(path):
            pass
        writer_connection = manager._write_conns[path_key]
        failure = pyodbc.OperationalError("HY000", "rollback refused")
        with self.assertNoLogs(_MANAGER_MODULE, level="ERROR"):
            with self.assertRaises(pyodbc.OperationalError) as raised:
                with manager.connection(path):
                    writer_connection.rollback_error = failure
                    raise ValueError("body failed")
        self.assertIs(raised.exception, failure)
        self.assertIsInstance(raised.exception.__context__, ValueError)
        self.assertTrue(writer_connection.closed)
        manager.close()
        self.assert_all_resources_released()

    def test_an_ordinary_error_after_a_caught_failed_rollback_keeps_the_handle(self):
        # Only driver errors and interrupts reach the replacement decision: an
        # ordinary Exception never evicts, whatever wrapper.rollback_failed says.
        for error_type in (ValueError, RuntimeError, KeyError):
            with self.subTest(error=error_type.__name__):
                manager = MdbConnectionManager()
                writer = MdbWriter(conn_manager=manager)
                path = f"ordinary-after-failed-rollback-{error_type.__name__}.mdb"
                handle = self._warm_writer_handle(writer, path)
                with self.assertRaises(error_type):
                    with manager.connection(path, autocommit=False) as connection:
                        handle.rollback_error = pyodbc.OperationalError(
                            "HY000", "refused"
                        )
                        try:
                            connection.rollback()
                        except pyodbc.Error:
                            pass
                        self.assertTrue(connection.rollback_failed)
                        raise error_type("not a driver error")
                self.assertFalse(handle.closed)
                manager.close()
        self.assert_all_resources_released()

    def test_a_connect_failure_that_is_not_an_operational_error_is_not_translated(self):
        failure = pyodbc.ProgrammingError(
            "08004", "[Microsoft][ODBC] Too many client tasks. (-1036)"
        )
        manager = MdbConnectionManager()
        with patch(f"{_MANAGER_MODULE}.pyodbc.connect", side_effect=failure):
            with self.assertRaises(pyodbc.ProgrammingError) as raised:
                with manager.connection("untranslated.mdb"):
                    pass
        self.assertIs(raised.exception, failure)
        manager.close()

    def test_a_non_driver_ordinary_error_does_not_run_the_replacement_handler(self):
        # Control: a ValueError never evicts the handle, even with a dead probe.
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        path = "ordinary-valueerror.mdb"
        handle = self._warm_writer_handle(writer, path)
        with self.assertRaises(ValueError):
            with manager.connection(path, autocommit=False):
                handle.unhealthy = True
                raise ValueError("not a driver error")
        self.assertFalse(handle.closed)
        manager.close()
        self.assert_all_resources_released()

    def test_an_interrupt_in_a_borrowed_writer_read_lease_keeps_a_cleanly_rolled_back_handle(
        self,
    ):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        path = "borrowed-interrupt-clean.mdb"
        path_key = os.path.normcase(os.path.abspath(path))
        with writer._connection(path):
            pass
        writer_connection = manager._write_conns[path_key]
        before = self.connect.counts.rollbacks
        with self.assertRaises(SystemExit):
            with manager.connection(path):
                raise SystemExit(3)
        self.assertEqual(self.connect.counts.rollbacks, before + 1)
        self.assertIs(manager._write_conns[path_key], writer_connection)
        self.assertFalse(writer_connection.closed)
        self.assertEqual(manager._active_leases, {})
        manager.close()
        self.assert_all_resources_released()

    def test_successful_rollback_of_a_borrowed_writer_read_lease_keeps_the_handle(
        self,
    ):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        path = "borrowed-clean.mdb"
        path_key = os.path.normcase(os.path.abspath(path))
        with writer._connection(path):
            pass
        writer_connection = manager._write_conns[path_key]
        before = self.connect.counts.rollbacks
        with manager.connection(path) as connection:
            self.assertIs(connection._conn, writer_connection)
        self.assertEqual(self.connect.counts.rollbacks, before + 1)
        self.assertIs(manager._write_conns[path_key], writer_connection)
        self.assertFalse(writer_connection.closed)
        manager.close()
        self.assert_all_resources_released()

    def test_absolute_and_case_normalized_path_spellings_share_one_identity(self):
        manager = MdbConnectionManager()
        absolute = os.path.abspath("Identity.mdb")
        spellings = (
            "Identity.mdb",
            absolute.upper(),
            absolute.lower(),
            os.path.join(".", "sub", "..", "IDENTITY.MDB"),
        )
        first_connection = None
        for spelling in spellings:
            with self.subTest(spelling=spelling):
                with manager.connection(spelling) as connection:
                    if first_connection is None:
                        first_connection = connection._conn
                    self.assertIs(connection._conn, first_connection)
        self.assertEqual(self.connect.counts.connections_opened, 1)
        self.assertEqual(list(manager._read_conns), [os.path.normcase(absolute)])
        self.assertEqual(list(manager._path_locks), [os.path.normcase(absolute)])
        manager.close_database(absolute.upper())
        self.assertTrue(first_connection.closed)
        self.assertEqual(manager._read_conns, {})
        self.assert_all_resources_released()

    def test_path_lock_serializes_leases_spelled_with_different_case(self):
        manager = MdbConnectionManager()
        contended = _ContendedRLock()
        manager._path_locks[os.path.normcase(os.path.abspath("Lock-Identity.mdb"))] = (
            contended
        )
        first_entered = threading.Event()
        release_first = threading.Event()
        second_entered = threading.Event()

        def first_work() -> None:
            with manager.connection("Lock-Identity.mdb"):
                first_entered.set()
                release_first.wait(timeout=2.0)

        def second_work() -> None:
            with manager.connection(os.path.abspath("LOCK-IDENTITY.MDB")):
                second_entered.set()

        first = threading.Thread(target=first_work)
        second = threading.Thread(target=second_work)
        first.start()
        self.assertTrue(first_entered.wait(timeout=2.0))
        second.start()
        self.assertTrue(contended.contended.wait(timeout=2.0))
        self.assertFalse(second_entered.is_set())
        release_first.set()
        first.join()
        second.join()
        self.assertTrue(second_entered.is_set())
        self.assertEqual(self.connect.counts.connections_opened, 1)
        manager.close()
        self.assert_all_resources_released()

    def test_nested_write_leases_share_one_handle_at_any_depth(self):
        manager = MdbConnectionManager()
        path_key = os.path.normcase(os.path.abspath("nested-write.mdb"))
        with manager.connection("nested-write.mdb", autocommit=False) as outer:
            with manager.connection("nested-write.mdb", autocommit=False) as middle:
                with manager.connection("nested-write.mdb", autocommit=False) as inner:
                    self.assertIs(outer._conn, middle._conn)
                    self.assertIs(outer._conn, inner._conn)
                self.assertEqual(manager._active_leases[path_key], (False, 2))
            self.assertEqual(manager._active_leases[path_key], (False, 1))
        self.assertEqual(manager._active_leases, {})
        self.assertEqual(self.connect.counts.connections_opened, 1)
        self.assertEqual(list(manager._write_conns), [path_key])
        self.assertEqual(manager._read_conns, {})
        manager.close()
        self.assert_all_resources_released()

    def test_nested_read_leases_share_one_handle_at_any_depth(self):
        manager = MdbConnectionManager()
        path_key = os.path.normcase(os.path.abspath("nested-read.mdb"))
        with manager.connection("nested-read.mdb") as outer:
            with manager.connection("nested-read.mdb"):
                with manager.connection("nested-read.mdb") as inner:
                    self.assertIs(outer._conn, inner._conn)
                self.assertEqual(manager._active_leases[path_key], (True, 2))
        self.assertEqual(manager._active_leases, {})
        self.assertEqual(self.connect.counts.connections_opened, 1)
        manager.close()
        self.assert_all_resources_released()

    def test_writer_lease_never_borrows_the_committed_writer_read_preference(self):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        path = "preference-write.mdb"
        path_key = os.path.normcase(os.path.abspath(path))
        with writer._connection(path):
            pass
        writer_connection = manager._write_conns[path_key]
        self.assertIn(path_key, manager._writer_read_paths)
        rollbacks = self.connect.counts.rollbacks
        with manager.connection(path, autocommit=False) as connection:
            self.assertIs(connection._conn, writer_connection)
        # A writer is not a borrowed reader: no rollback at exit, same pool.
        self.assertEqual(self.connect.counts.rollbacks, rollbacks)
        self.assertIs(manager._write_conns[path_key], writer_connection)
        self.assertFalse(writer_connection.closed)
        # With no cached writer yet, the preference must not redirect a writer
        # lease into the read pool either.
        manager.close_write_connections()
        manager.use_committed_writer_for_reads(path)
        with manager.connection(path, autocommit=False) as connection:
            new_writer = connection._conn
        self.assertEqual(list(manager._write_conns), [path_key])
        self.assertIs(manager._write_conns[path_key], new_writer)
        self.assertNotIn(path_key, manager._read_conns)
        self.assertIn(path_key, manager._writer_read_paths)
        manager.close()
        self.assert_all_resources_released()

    def test_read_after_writer_loss_replaces_the_stale_read_snapshot(self):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        path = "writer-lost.mdb"
        path_key = os.path.normcase(os.path.abspath(path))
        with manager.connection(path):
            pass
        stale_reader = manager._read_conns[path_key]
        with writer._connection(path):
            pass
        manager.close_write_connections()
        self.assertIn(path_key, manager._writer_read_paths)
        with manager.connection(path) as connection:
            fresh_reader = connection._conn
        self.assertIsNot(fresh_reader, stale_reader)
        self.assertTrue(stale_reader.closed)
        self.assertNotIn(path_key, manager._writer_read_paths)
        self.assertEqual(manager._write_conns, {})
        self.assertIs(manager._read_conns[path_key], fresh_reader)
        self.assertEqual(self.connect.counts.connections_opened, 3)
        manager.close()
        self.assert_all_resources_released()

    def test_maintenance_closes_only_the_reserved_database(self):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        for path in ("reserved.mdb", "bystander.mdb"):
            with manager.connection(path):
                pass
            with writer._connection(path):
                pass
        reserved_key = os.path.normcase(os.path.abspath("reserved.mdb"))
        bystander_key = os.path.normcase(os.path.abspath("bystander.mdb"))
        bystanders = (
            manager._read_conns[bystander_key],
            manager._write_conns[bystander_key],
        )
        reserved = (
            manager._read_conns[reserved_key],
            manager._write_conns[reserved_key],
        )
        with manager.maintenance("RESERVED.mdb"):
            self.assertTrue(all(connection.closed for connection in reserved))
            self.assertFalse(any(connection.closed for connection in bystanders))
            self.assertEqual(self.connect.counts.active_connections, 2)
            with manager.connection("bystander.mdb") as connection:
                self.assertIs(connection._conn, bystanders[1])
        self.assertEqual(manager._maintenance_paths, set())
        manager.close()
        self.assert_all_resources_released()


class MdbConnectionManagerHandleReplacementTests(unittest.TestCase):
    """Second pass: when a physical handle is probed, flagged, closed or kept."""

    def setUp(self) -> None:
        self.connect = _FakeConnect()
        self.connect_patch = patch(
            "ost_visualizer.infrastructure.mdb.connection_manager.pyodbc.connect",
            self.connect,
        )
        self.connect_patch.start()

    def tearDown(self) -> None:
        self.connect_patch.stop()

    def assert_all_resources_released(self) -> None:
        counts = self.connect.counts
        self.assertEqual(counts.connections_opened, counts.connections_closed)
        self.assertEqual(counts.active_connections, 0)
        self.assertEqual(counts.cursors_created, counts.cursors_closed)

    @staticmethod
    def _fail_close_once(connection, attempts):
        original_close = connection.close

        def close():
            attempts.append(True)
            if len(attempts) == 1:
                raise pyodbc.OperationalError("HY000", "connection close failed")
            original_close()

        connection.close = close

    def test_idle_handle_that_died_is_replaced_by_the_lease_probe(self):
        manager = MdbConnectionManager()
        with manager.connection("idle-dead.mdb") as connection:
            first_connection = connection._conn
        first_connection.unhealthy = True
        with manager.connection("idle-dead.mdb") as connection:
            self.assertIsNot(connection._conn, first_connection)
            connection.cursor().execute("SELECT")
        self.assertTrue(first_connection.closed)
        self.assertNotIn(id(first_connection), manager._unhealthy_connection_ids)
        self.assertEqual(self.connect.counts.connections_opened, 2)
        # The probe cursors are closed immediately, not by the later shutdown.
        self.assertEqual(self.connect.counts.active_cursors, 0)
        manager.close()
        self.assert_all_resources_released()

    def test_probe_failure_keeps_the_handle_flagged_until_its_close_succeeds(self):
        manager = MdbConnectionManager()
        path_key = os.path.normcase(os.path.abspath("flaky.mdb"))
        with manager.connection("flaky.mdb") as connection:
            first_connection = connection._conn
        attempts = []
        self._fail_close_once(first_connection, attempts)
        first_connection.fail_cursor_open_once = True
        with self.assertRaisesRegex(pyodbc.OperationalError, "close failed"):
            with manager.connection("flaky.mdb"):
                self.fail("lease granted on a handle that failed its probe")
        self.assertEqual(manager._active_leases, {})
        self.assertIs(manager._read_conns[path_key], first_connection)
        self.assertIn(id(first_connection), manager._unhealthy_connection_ids)
        # The handle would pass the probe now, but a flagged handle must be
        # closed (retried) and replaced, never reused.
        with manager.connection("flaky.mdb") as connection:
            self.assertIsNot(connection._conn, first_connection)
        self.assertEqual(len(attempts), 2)
        self.assertTrue(first_connection.closed)
        self.assertNotIn(id(first_connection), manager._unhealthy_connection_ids)
        manager.close()
        self.assert_all_resources_released()

    def test_connection_class_error_with_failed_close_stays_owned_and_is_retried(self):
        manager = MdbConnectionManager()
        path_key = os.path.normcase(os.path.abspath("owned.mdb"))
        with manager.connection("owned.mdb") as connection:
            first_connection = connection._conn
        attempts = []
        self._fail_close_once(first_connection, attempts)
        with self.assertRaisesRegex(
            pyodbc.OperationalError, "communication link"
        ) as raised:
            with manager.connection("owned.mdb") as connection:
                connection.cursor().execute("RAISE_CONNECTION_CLASS_ERROR")
        self.assertIn(
            "The invalid MDB connection could not be closed: "
            "('HY000', 'connection close failed')",
            raised.exception.__notes__,
        )
        self.assertIs(manager._read_conns[path_key], first_connection)
        self.assertIn(id(first_connection), manager._unhealthy_connection_ids)
        self.assertEqual(manager._active_leases, {})
        # The probe would pass (the fake stays healthy); only the flag forces
        # the retried close and the replacement.
        with manager.connection("owned.mdb") as connection:
            self.assertIsNot(connection._conn, first_connection)
        self.assertEqual(len(attempts), 2)
        self.assertTrue(first_connection.closed)
        self.assertNotIn(id(first_connection), manager._unhealthy_connection_ids)
        manager.close()
        self.assert_all_resources_released()

    def test_statement_error_on_a_dead_handle_replaces_it_via_the_probe(self):
        manager = MdbConnectionManager()
        with self.assertRaisesRegex(pyodbc.OperationalError, "statement failed"):
            with manager.connection("dead-statement.mdb") as connection:
                first_connection = connection._conn
                connection.cursor().execute("RAISE_DEAD_CONNECTION_STATEMENT_ERROR")
        self.assertTrue(first_connection.closed)
        self.assertEqual(manager._read_conns, {})
        with manager.connection("dead-statement.mdb") as connection:
            self.assertIsNot(connection._conn, first_connection)
        manager.close()
        self.assert_all_resources_released()

    def test_statement_error_on_a_healthy_handle_closes_its_probe_cursor_at_once(self):
        manager = MdbConnectionManager()
        with self.assertRaisesRegex(pyodbc.ProgrammingError, "table does not exist"):
            with manager.connection("healthy-statement.mdb") as connection:
                connection.cursor().execute("RAISE_SCHEMA_ERROR")
        self.assertEqual(self.connect.counts.active_cursors, 0)
        self.assertEqual(self.connect.counts.connections_opened, 1)
        manager.close()
        self.assert_all_resources_released()

    def test_flagged_writer_is_replaced_without_touching_the_reader(self):
        manager = MdbConnectionManager()
        path_key = os.path.normcase(os.path.abspath("flagged-writer.mdb"))
        with manager.connection("flagged-writer.mdb"):
            pass
        with manager.connection("flagged-writer.mdb", autocommit=False):
            pass
        reader_connection = manager._read_conns[path_key]
        writer_connection = manager._write_conns[path_key]
        manager._unhealthy_connection_ids.add(id(writer_connection))
        with manager.connection("flagged-writer.mdb", autocommit=False) as connection:
            self.assertIsNot(connection._conn, writer_connection)
            new_writer = connection._conn
        self.assertTrue(writer_connection.closed)
        self.assertFalse(reader_connection.closed)
        self.assertIs(manager._read_conns[path_key], reader_connection)
        self.assertIs(manager._write_conns[path_key], new_writer)
        manager.close()
        self.assert_all_resources_released()

    def test_a_flagged_or_dead_writer_borrowed_for_reads_also_drops_the_read_snapshot(
        self,
    ):
        for label, condemn in (
            (
                "flagged by an earlier failed close",
                lambda manager, writer: manager._unhealthy_connection_ids.add(
                    id(writer)
                ),
            ),
            (
                "dead at the probe",
                lambda manager, writer: setattr(writer, "unhealthy", True),
            ),
        ):
            with self.subTest(case=label):
                self.connect.counts = _LifecycleCounts()
                manager = MdbConnectionManager()
                writer = MdbWriter(conn_manager=manager)
                path = "borrowed-condemned.mdb"
                path_key = os.path.normcase(os.path.abspath(path))
                with manager.connection(path):
                    pass
                stale_reader = manager._read_conns[path_key]
                with writer._connection(path):
                    pass
                condemned_writer = manager._write_conns[path_key]
                self.assertIn(path_key, manager._writer_read_paths)
                condemn(manager, condemned_writer)
                rollbacks = self.connect.counts.rollbacks
                with manager.connection(path) as connection:
                    fresh_reader = connection._conn
                self.assertTrue(condemned_writer.closed)
                self.assertTrue(stale_reader.closed)
                self.assertIsNot(fresh_reader, stale_reader)
                self.assertEqual(manager._write_conns, {})
                self.assertIs(manager._read_conns[path_key], fresh_reader)
                self.assertNotIn(path_key, manager._writer_read_paths)
                # The replacement is a plain read handle, not a borrowed writer.
                self.assertEqual(self.connect.counts.rollbacks, rollbacks)
                manager.close()
                self.assert_all_resources_released()

    def test_read_lease_without_a_read_handle_borrows_and_rolls_back_the_writer(self):
        manager = MdbConnectionManager()
        path_key = os.path.normcase(os.path.abspath("borrow.mdb"))
        with manager.connection("borrow.mdb", autocommit=False):
            pass
        writer_connection = manager._write_conns[path_key]
        rollbacks = self.connect.counts.rollbacks
        with manager.connection("borrow.mdb") as connection:
            self.assertIs(connection._conn, writer_connection)
            self.assertEqual(manager._read_conns, {})
            self.assertEqual(self.connect.counts.rollbacks, rollbacks)
        self.assertEqual(self.connect.counts.rollbacks, rollbacks + 1)
        self.assertIs(manager._write_conns[path_key], writer_connection)
        failure = pyodbc.OperationalError("HY000", "rollback refused")
        with self.assertRaises(pyodbc.OperationalError) as raised:
            with manager.connection("borrow.mdb") as connection:
                writer_connection.rollback_error = failure
        self.assertIs(raised.exception, failure)
        self.assertTrue(writer_connection.closed)
        self.assertEqual((manager._read_conns, manager._write_conns), ({}, {}))
        manager.close()
        self.assert_all_resources_released()

    def test_write_handle_close_failures_stay_owned_and_are_all_reported(self):
        manager = MdbConnectionManager()
        paths = ("first.mdb", "second.mdb", "third.mdb")
        keys = [os.path.normcase(os.path.abspath(path)) for path in paths]
        for path in paths:
            with manager.connection(path):
                pass
            with manager.connection(path, autocommit=False):
                pass
        readers = [manager._read_conns[key] for key in keys]
        writers = [manager._write_conns[key] for key in keys]
        attempts = {0: [], 1: [], 2: []}
        for index in (0, 1):
            self._fail_close_once(writers[index], attempts[index])
        with self.assertRaises(ExceptionGroup) as raised:
            manager.close_write_connections()
        self.assertEqual(len(raised.exception.exceptions), 2)
        self.assertEqual(sorted(manager._write_conns), sorted(keys[:2]))
        self.assertTrue(writers[2].closed)
        self.assertFalse(any(reader.closed for reader in readers))
        # A single failure is raised as itself, then the retry succeeds.
        attempts = []
        self._fail_close_once(writers[0], attempts)
        with self.assertRaisesRegex(pyodbc.OperationalError, "close failed"):
            manager.close_write_connections()
        self.assertEqual(list(manager._write_conns), [keys[0]])
        manager.close_write_connections()
        self.assertEqual(manager._write_conns, {})
        self.assertTrue(all(writer.closed for writer in writers))
        manager.close()
        self.assert_all_resources_released()

    def test_shutdown_forgets_path_locks_and_reader_preferences(self):
        manager = MdbConnectionManager()
        with manager.connection("forget.mdb"):
            pass
        manager.use_committed_writer_for_reads("preference-only.mdb")
        self.assertEqual(len(manager._path_locks), 2)
        self.assertEqual(len(manager._writer_read_paths), 1)
        manager.close()
        self.assertEqual(manager._path_locks, {})
        self.assertEqual(manager._writer_read_paths, set())
        self.assertEqual(manager._unhealthy_connection_ids, set())
        self.assert_all_resources_released()

    def test_client_task_exhaustion_is_recognised_by_either_driver_marker(self):
        failures = (
            pyodbc.OperationalError("08004", "[Microsoft] Too many client tasks."),
            pyodbc.OperationalError("08004", "driver failure (-1036)"),
            pyodbc.OperationalError("08004", "TOO MANY CLIENT TASKS"),
            pyodbc.OperationalError("[08004] Too Many Client Tasks (-1036)"),
        )
        for failure in failures:
            with self.subTest(failure=failure.args):
                with patch(
                    "ost_visualizer.infrastructure.mdb.connection_manager."
                    "pyodbc.connect",
                    side_effect=failure,
                ) as connect:
                    manager = MdbConnectionManager()
                    with self.assertRaisesRegex(
                        DatabaseConnectionUnavailableError, "restart OST Visualizer"
                    ) as raised:
                        with manager.connection("exhausted-variants.mdb"):
                            self.fail("lease granted")
                self.assertIs(raised.exception.__cause__, failure)
                self.assertEqual(connect.call_count, 1)

    def test_evicted_handle_is_never_left_flagged_after_a_second_failure(self):
        # A connection-class error evicts and closes the handle; a failed cursor
        # close in the same lease must not flag it again. Flags are id()s: a
        # stale one would condemn whatever healthy handle later reuses the id.
        manager = MdbConnectionManager()
        with manager.connection("double-failure.mdb") as connection:
            first_connection = connection._conn
        with self.assertRaisesRegex(pyodbc.OperationalError, "communication link"):
            with manager.connection("double-failure.mdb") as connection:
                connection._conn.fail_next_cursor_close = True
                connection.cursor().execute("RAISE_CONNECTION_CLASS_ERROR")
        self.assertTrue(first_connection.closed)
        self.assertEqual(manager._read_conns, {})
        self.assertEqual(manager._unhealthy_connection_ids, set())
        # A failed rollback of a borrowed writer plus a failed cursor close.
        with manager.connection("double-failure.mdb", autocommit=False) as connection:
            writer_connection = connection._conn
        with self.assertRaises(pyodbc.OperationalError):
            with manager.connection("double-failure.mdb") as connection:
                writer_connection.fail_next_cursor_close = True
                connection.cursor().execute("SELECT")
                writer_connection.rollback_error = pyodbc.OperationalError(
                    "HY000", "rollback refused"
                )
        self.assertTrue(writer_connection.closed)
        self.assertEqual(manager._write_conns, {})
        self.assertEqual(manager._unhealthy_connection_ids, set())
        manager.close()
        self.assert_all_resources_released()


class MdbConnectionManagerNestedLeaseEvictionTests(unittest.TestCase):
    """Decision D7: a failed cursor cleanup condemns the shared handle at once but
    the physical close waits for the outermost lease of that handle."""

    def setUp(self) -> None:
        self.connect = _FakeConnect()
        self.connect_patch = patch(
            "ost_visualizer.infrastructure.mdb.connection_manager.pyodbc.connect",
            self.connect,
        )
        self.connect_patch.start()

    def tearDown(self) -> None:
        self.connect_patch.stop()

    @staticmethod
    def _count_closes(connection, fail_first=False):
        attempts = []
        original_close = connection.close

        def close():
            attempts.append(True)
            if fail_first and len(attempts) == 1:
                raise pyodbc.OperationalError("HY000", "connection close failed")
            original_close()

        connection.close = close
        return attempts

    @staticmethod
    def _fail_inner_cursor_cleanup(lease):
        lease._conn.fail_next_cursor_close = True
        lease.cursor().execute("SELECT")

    def assert_all_resources_released(self) -> None:
        counts = self.connect.counts
        self.assertEqual(counts.connections_opened, counts.connections_closed)
        self.assertEqual(counts.active_connections, 0)
        self.assertEqual(counts.cursors_created, counts.cursors_closed)

    def test_nested_cursor_cleanup_failure_defers_the_close_to_the_outermost_lease(
        self,
    ):
        manager = MdbConnectionManager()
        path_key = os.path.normcase(os.path.abspath("nested-cleanup.mdb"))
        with manager.connection("nested-cleanup.mdb") as outer:
            shared = outer._conn
            closes = self._count_closes(shared)
            outer_cursor = outer.cursor()
            with manager.connection("nested-cleanup.mdb") as inner:
                self._fail_inner_cursor_cleanup(inner)
            # The inner lease ended with a failed cursor close: the handle is
            # condemned for any later use but still open under the outer lease.
            self.assertFalse(shared.closed)
            self.assertEqual(closes, [])
            self.assertIs(manager._read_conns[path_key], shared)
            self.assertIn(id(shared), manager._unhealthy_connection_ids)
            self.assertEqual(manager._active_leases[path_key], (True, 1))
            outer_cursor.execute("SELECT")
            self.assertEqual(outer_cursor.fetchall(), [("row",)])
            outer.cursor().execute("SELECT")
        self.assertTrue(shared.closed)
        self.assertEqual(len(closes), 1)
        self.assertEqual(manager._read_conns, {})
        self.assertEqual(manager._unhealthy_connection_ids, set())
        self.assertEqual(manager._deferred_eviction_ids, set())
        self.assertEqual(manager._active_leases, {})
        with manager.connection("nested-cleanup.mdb") as fresh:
            self.assertIsNot(fresh._conn, shared)
        self.assertEqual(self.connect.counts.connections_opened, 2)
        manager.close()
        self.assert_all_resources_released()

    def test_condemned_shared_handle_is_never_granted_to_another_nested_lease(self):
        manager = MdbConnectionManager()
        path_key = os.path.normcase(os.path.abspath("nested-refused.mdb"))
        with manager.connection("nested-refused.mdb") as outer:
            shared = outer._conn
            closes = self._count_closes(shared)
            with manager.connection("nested-refused.mdb") as inner:
                self._fail_inner_cursor_cleanup(inner)
            with self.assertRaisesRegex(RuntimeError, "cursor cleanup failed"):
                with manager.connection("nested-refused.mdb"):
                    self.fail("nested lease granted on a condemned handle")
            # The refusal neither opened a second handle, closed the shared one
            # under the outer lease, nor unbalanced the lease depth.
            self.assertFalse(shared.closed)
            self.assertEqual(closes, [])
            self.assertEqual(manager._active_leases[path_key], (True, 1))
            self.assertEqual(self.connect.counts.connections_opened, 1)
            outer.cursor().execute("SELECT")
        self.assertEqual(len(closes), 1)
        self.assertTrue(shared.closed)
        self.assertEqual(manager._active_leases, {})
        manager.close()
        self.assert_all_resources_released()

    def test_cleanup_failure_at_depth_three_waits_for_depth_zero(self):
        manager = MdbConnectionManager()
        path_key = os.path.normcase(os.path.abspath("nested-deep.mdb"))
        with manager.connection("nested-deep.mdb") as outer:
            shared = outer._conn
            closes = self._count_closes(shared)
            with manager.connection("nested-deep.mdb"):
                with manager.connection("nested-deep.mdb") as innermost:
                    self._fail_inner_cursor_cleanup(innermost)
                self.assertEqual(manager._active_leases[path_key], (True, 2))
                self.assertFalse(shared.closed)
            # The middle lease also ended: depth 1 is still an outer lease.
            self.assertEqual(manager._active_leases[path_key], (True, 1))
            self.assertFalse(shared.closed)
            self.assertEqual(closes, [])
        self.assertTrue(shared.closed)
        self.assertEqual(len(closes), 1)
        manager.close()
        self.assert_all_resources_released()

    def test_failed_deferred_close_stays_owned_and_is_retried_by_the_next_lease(self):
        manager = MdbConnectionManager()
        path_key = os.path.normcase(os.path.abspath("nested-retry.mdb"))
        with manager.connection("nested-retry.mdb") as outer:
            shared = outer._conn
            closes = self._count_closes(shared, fail_first=True)
            with manager.connection("nested-retry.mdb") as inner:
                self._fail_inner_cursor_cleanup(inner)
            self.assertEqual(closes, [])
        # Exactly one close attempt at the outermost release; it failed, so the
        # handle stays owned and flagged and the failure is not raised over the
        # result of the caller.
        self.assertEqual(len(closes), 1)
        self.assertFalse(shared.closed)
        self.assertIs(manager._read_conns[path_key], shared)
        self.assertIn(id(shared), manager._unhealthy_connection_ids)
        self.assertEqual(manager._deferred_eviction_ids, set())
        self.assertEqual(manager._active_leases, {})
        with manager.connection("nested-retry.mdb") as fresh:
            self.assertIsNot(fresh._conn, shared)
        self.assertEqual(len(closes), 2)
        self.assertTrue(shared.closed)
        self.assertNotIn(id(shared), manager._unhealthy_connection_ids)
        manager.close()
        self.assert_all_resources_released()

    def test_nested_write_lease_cleanup_failure_defers_the_writer_close(self):
        manager = MdbConnectionManager()
        path_key = os.path.normcase(os.path.abspath("nested-writer.mdb"))
        with manager.connection("nested-writer.mdb", autocommit=False) as outer:
            shared = outer._conn
            closes = self._count_closes(shared)
            outer.cursor().execute("INSERT_PENDING")
            with manager.connection("nested-writer.mdb", autocommit=False) as inner:
                self._fail_inner_cursor_cleanup(inner)
            self.assertFalse(shared.closed)
            self.assertIs(manager._write_conns[path_key], shared)
            outer.commit()
        self.assertEqual(self.connect.counts.committed_rows, ["pending"])
        self.assertTrue(shared.closed)
        self.assertEqual(len(closes), 1)
        self.assertEqual(manager._write_conns, {})
        manager.close()
        self.assert_all_resources_released()

    def test_nested_borrowed_writer_read_cleanup_failure_defers_the_writer_close(
        self,
    ):
        manager = MdbConnectionManager()
        path_key = os.path.normcase(os.path.abspath("nested-borrowed.mdb"))
        with manager.connection("nested-borrowed.mdb", autocommit=False) as writer:
            writer_connection = writer._conn
        closes = self._count_closes(writer_connection)
        with manager.connection("nested-borrowed.mdb") as outer:
            self.assertIs(outer._conn, writer_connection)
            with manager.connection("nested-borrowed.mdb") as inner:
                self._fail_inner_cursor_cleanup(inner)
            self.assertFalse(writer_connection.closed)
            self.assertEqual(closes, [])
            self.assertIs(manager._write_conns[path_key], writer_connection)
        self.assertTrue(writer_connection.closed)
        self.assertEqual(len(closes), 1)
        self.assertEqual(manager._write_conns, {})
        manager.close()
        self.assert_all_resources_released()

    def test_outermost_cleanup_failure_still_evicts_immediately(self):
        manager = MdbConnectionManager()
        with manager.connection("outermost-cleanup.mdb") as outer:
            shared = outer._conn
            closes = self._count_closes(shared)
            self._fail_inner_cursor_cleanup(outer)
            self.assertFalse(shared.closed)
        self.assertTrue(shared.closed)
        self.assertEqual(len(closes), 1)
        self.assertEqual(manager._read_conns, {})
        self.assertEqual(manager._unhealthy_connection_ids, set())
        manager.close()
        self.assert_all_resources_released()

    def test_outer_error_and_nested_cleanup_failure_close_the_handle_once(self):
        manager = MdbConnectionManager()
        with self.assertRaisesRegex(ValueError, "outer failed"):
            with manager.connection("nested-error.mdb") as outer:
                shared = outer._conn
                closes = self._count_closes(shared)
                with manager.connection("nested-error.mdb") as inner:
                    self._fail_inner_cursor_cleanup(inner)
                self.assertFalse(shared.closed)
                raise ValueError("outer failed")
        self.assertTrue(shared.closed)
        self.assertEqual(len(closes), 1)
        self.assertEqual(manager._unhealthy_connection_ids, set())
        manager.close()
        self.assert_all_resources_released()


class MdbConnectionManagerNestedLeaseFailureTests(unittest.TestCase):
    """Decision D15: in a nested lease a connection-class error, a failed
    rollback or a failed per-lease health probe condemn the shared handle exactly
    like a failed cursor cleanup (D7): flagged at once, closed once when the
    outermost lease ends, never closed under the outer lease."""

    KINDS = ("reader", "writer", "borrowed_writer_read")
    TRIGGERS = ("connection_error", "failed_rollback", "probe_failure")
    _count_closes = staticmethod(
        MdbConnectionManagerNestedLeaseEvictionTests._count_closes
    )

    def setUp(self) -> None:
        self.connect = _FakeConnect()
        self.connect_patch = patch(
            "ost_visualizer.infrastructure.mdb.connection_manager.pyodbc.connect",
            self.connect,
        )
        self.connect_patch.start()

    def tearDown(self) -> None:
        self.connect_patch.stop()

    def assert_all_resources_released(self) -> None:
        counts = self.connect.counts
        self.assertEqual(counts.connections_opened, counts.connections_closed)
        self.assertEqual(counts.active_connections, 0)
        self.assertEqual(counts.cursors_created, counts.cursors_closed)

    def _prepare(self, manager, path, kind):
        """Return (open_lease, pool, autocommit) for one lease kind. The borrowed
        kind first leaves a committed writer so read leases borrow it."""
        if kind == "borrowed_writer_read":
            with manager.connection(path, autocommit=False):
                pass
        autocommit = kind != "writer"
        pool = manager._read_conns if kind == "reader" else manager._write_conns
        return (
            (lambda: manager.connection(path, autocommit=autocommit)),
            pool,
            autocommit,
        )

    def _trigger(self, name, open_lease, shared):
        """Run one nested lease that hits the failure and contain its error."""
        if name == "connection_error":
            with self.assertRaisesRegex(pyodbc.OperationalError, "communication link"):
                with open_lease() as inner:
                    inner.cursor().execute("RAISE_CONNECTION_CLASS_ERROR")
        elif name == "failed_rollback":
            failure = pyodbc.OperationalError("HY000", "rollback refused")
            with self.assertRaises(pyodbc.OperationalError) as raised:
                with open_lease() as inner:
                    shared.rollback_error = failure
                    inner.rollback()
            self.assertIs(raised.exception, failure)
        else:
            shared.fail_cursor_open_once = True
            with self.assertRaisesRegex(
                RuntimeError, "cursor cleanup failed"
            ) as raised:
                with open_lease():
                    self.fail("nested lease granted on a handle that failed its probe")
            self.assertIsInstance(raised.exception.__cause__, pyodbc.OperationalError)

    def _matrix(self, test):
        for kind in self.KINDS:
            for trigger in self.TRIGGERS:
                with self.subTest(kind=kind, trigger=trigger):
                    self.connect.counts = _LifecycleCounts()
                    manager = MdbConnectionManager()
                    path = f"nested-{kind}-{trigger}.mdb"
                    open_lease, pool, autocommit = self._prepare(manager, path, kind)
                    test(
                        manager,
                        os.path.normcase(os.path.abspath(path)),
                        open_lease,
                        pool,
                        autocommit,
                        trigger,
                    )
                    manager.close()
                    self.assert_all_resources_released()

    def test_nested_failure_condemns_the_shared_handle_until_the_outermost_lease_ends(
        self,
    ):
        def scenario(manager, path_key, open_lease, pool, autocommit, trigger):
            with open_lease() as outer:
                shared = outer._conn
                self.assertIs(pool[path_key], shared)
                closes = self._count_closes(shared)
                outer_cursor = outer.cursor()
                self._trigger(trigger, open_lease, shared)
                # Condemned for any later use, still open and owned under the
                # outer lease, whose own cursor keeps working; depth unwound.
                self.assertFalse(shared.closed)
                self.assertEqual(closes, [])
                self.assertIs(pool[path_key], shared)
                self.assertIn(id(shared), manager._unhealthy_connection_ids)
                self.assertIn(id(shared), manager._deferred_eviction_ids)
                self.assertEqual(manager._active_leases[path_key], (autocommit, 1))
                outer_cursor.execute("SELECT")
                self.assertEqual(outer_cursor.fetchall(), [("row",)])
                # No further nested lease is granted on the condemned handle.
                with self.assertRaisesRegex(RuntimeError, "cursor cleanup failed"):
                    with open_lease():
                        self.fail("nested lease granted on a condemned handle")
                self.assertFalse(shared.closed)
                self.assertEqual(closes, [])
                self.assertEqual(manager._active_leases[path_key], (autocommit, 1))
                self.assertEqual(self.connect.counts.connections_opened, 1)
            self.assertTrue(shared.closed)
            self.assertEqual(len(closes), 1)
            self.assertEqual(pool, {})
            self.assertEqual(manager._unhealthy_connection_ids, set())
            self.assertEqual(manager._deferred_eviction_ids, set())
            self.assertEqual(manager._active_leases, {})
            with open_lease() as fresh:
                self.assertIsNot(fresh._conn, shared)

        self._matrix(scenario)

    def test_nested_failure_at_depth_three_waits_for_depth_zero(self):
        def scenario(manager, path_key, open_lease, pool, autocommit, trigger):
            with open_lease() as outer:
                shared = outer._conn
                closes = self._count_closes(shared)
                with open_lease():
                    self._trigger(trigger, open_lease, shared)
                    self.assertEqual(manager._active_leases[path_key], (autocommit, 2))
                    self.assertFalse(shared.closed)
                self.assertEqual(manager._active_leases[path_key], (autocommit, 1))
                self.assertFalse(shared.closed)
                self.assertEqual(closes, [])
            self.assertTrue(shared.closed)
            self.assertEqual(len(closes), 1)

        self._matrix(scenario)

    def test_failed_deferred_close_stays_owned_and_is_retried_by_the_next_lease(self):
        for trigger in self.TRIGGERS:
            with self.subTest(trigger=trigger):
                self.connect.counts = _LifecycleCounts()
                manager = MdbConnectionManager()
                path = f"nested-retry-{trigger}.mdb"
                path_key = os.path.normcase(os.path.abspath(path))
                with manager.connection(path) as outer:
                    shared = outer._conn
                    closes = self._count_closes(shared, fail_first=True)
                    self._trigger(trigger, lambda: manager.connection(path), shared)
                    self.assertEqual(closes, [])
                # One close attempt at the outermost release; it failed, so the
                # handle stays owned and flagged and nothing is raised over the
                # caller.
                self.assertEqual(len(closes), 1)
                self.assertFalse(shared.closed)
                self.assertIs(manager._read_conns[path_key], shared)
                self.assertIn(id(shared), manager._unhealthy_connection_ids)
                self.assertEqual(manager._deferred_eviction_ids, set())
                self.assertEqual(manager._active_leases, {})
                with manager.connection(path) as fresh:
                    self.assertIsNot(fresh._conn, shared)
                self.assertEqual(len(closes), 2)
                self.assertTrue(shared.closed)
                self.assertNotIn(id(shared), manager._unhealthy_connection_ids)
                manager.close()
                self.assert_all_resources_released()

    def test_outer_connection_error_after_a_nested_one_closes_the_handle_once(self):
        # The inner error propagates through the outer lease, which evicts the
        # handle at depth 1 itself; the deferred mark must not make the same
        # release attempt a second close when the first one failed.
        for fail_first in (False, True):
            with self.subTest(close_fails=fail_first):
                self.connect.counts = _LifecycleCounts()
                manager = MdbConnectionManager()
                path_key = os.path.normcase(os.path.abspath("nested-propagate.mdb"))
                with self.assertRaisesRegex(pyodbc.OperationalError, "communication"):
                    with manager.connection("nested-propagate.mdb") as outer:
                        shared = outer._conn
                        closes = self._count_closes(shared, fail_first=fail_first)
                        with manager.connection("nested-propagate.mdb") as inner:
                            inner.cursor().execute("RAISE_CONNECTION_CLASS_ERROR")
                self.assertEqual(len(closes), 1)
                self.assertEqual(shared.closed, not fail_first)
                self.assertEqual(manager._deferred_eviction_ids, set())
                self.assertEqual(manager._active_leases, {})
                if fail_first:
                    self.assertIs(manager._read_conns[path_key], shared)
                    self.assertIn(id(shared), manager._unhealthy_connection_ids)
                else:
                    self.assertEqual(manager._read_conns, {})
                    self.assertEqual(manager._unhealthy_connection_ids, set())
                manager.close()
                self.assert_all_resources_released()

    def test_nested_statement_error_and_plain_exception_leave_the_handle_healthy(
        self,
    ):
        # Positive control: only connection-class errors and failed rollbacks
        # condemn the handle; a statement error on a healthy handle does not.
        for kind in self.KINDS:
            with self.subTest(kind=kind):
                self.connect.counts = _LifecycleCounts()
                manager = MdbConnectionManager()
                path = f"nested-control-{kind}.mdb"
                path_key = os.path.normcase(os.path.abspath(path))
                open_lease, pool, autocommit = self._prepare(manager, path, kind)
                with open_lease() as outer:
                    shared = outer._conn
                    with self.assertRaisesRegex(pyodbc.ProgrammingError, "table"):
                        with open_lease() as inner:
                            inner.cursor().execute("RAISE_SCHEMA_ERROR")
                    with self.assertRaisesRegex(ValueError, "plain"):
                        with open_lease():
                            raise ValueError("plain")
                    self.assertEqual(manager._unhealthy_connection_ids, set())
                    self.assertEqual(manager._deferred_eviction_ids, set())
                    with open_lease() as again:
                        self.assertIs(again._conn, shared)
                    self.assertEqual(manager._active_leases[path_key], (autocommit, 1))
                self.assertFalse(shared.closed)
                self.assertIs(pool[path_key], shared)
                manager.close()
                self.assert_all_resources_released()

    def test_nested_error_on_a_handle_already_closed_by_someone_else_flags_nothing(
        self,
    ):
        # close_database() under an outer lease (same thread, re-entrant path
        # lock) removes the handle; a later nested connection error must not
        # flag or defer a handle the manager no longer owns (stale id()s).
        manager = MdbConnectionManager()
        path_key = os.path.normcase(os.path.abspath("nested-unowned.mdb"))
        with manager.connection("nested-unowned.mdb") as outer:
            shared = outer._conn
            with self.assertRaisesRegex(pyodbc.OperationalError, "communication"):
                with manager.connection("nested-unowned.mdb"):
                    manager.close_database("nested-unowned.mdb")
                    self.assertTrue(shared.closed)
                    raise pyodbc.OperationalError("08S01", "communication link failed")
            self.assertEqual(manager._unhealthy_connection_ids, set())
            self.assertEqual(manager._deferred_eviction_ids, set())
            self.assertEqual(manager._read_conns, {})
            self.assertEqual(manager._active_leases[path_key], (True, 1))
        self.assertEqual(manager._active_leases, {})
        manager.close()
        self.assert_all_resources_released()

    def test_nested_borrowed_writer_read_rollback_at_lease_end_condemns_the_writer(
        self,
    ):
        manager = MdbConnectionManager()
        path_key = os.path.normcase(os.path.abspath("nested-end-rollback.mdb"))
        with manager.connection("nested-end-rollback.mdb", autocommit=False):
            pass
        writer_connection = manager._write_conns[path_key]
        closes = self._count_closes(writer_connection)
        failure = pyodbc.OperationalError("HY000", "rollback refused")
        with manager.connection("nested-end-rollback.mdb") as outer:
            with self.assertRaises(pyodbc.OperationalError) as raised:
                with manager.connection("nested-end-rollback.mdb"):
                    # The borrowed lease rolls the writer back when it ends.
                    writer_connection.rollback_error = failure
            self.assertIs(raised.exception, failure)
            self.assertFalse(writer_connection.closed)
            self.assertEqual(closes, [])
            self.assertIn(id(writer_connection), manager._unhealthy_connection_ids)
            self.assertIn(id(writer_connection), manager._deferred_eviction_ids)
            self.assertIs(outer._conn, writer_connection)
        self.assertTrue(writer_connection.closed)
        self.assertEqual(len(closes), 1)
        self.assertEqual((manager._read_conns, manager._write_conns), ({}, {}))
        self.assertEqual(manager._unhealthy_connection_ids, set())
        manager.close()
        self.assert_all_resources_released()


class _TextOnlyExhaustionError(pyodbc.OperationalError):
    """An error whose marker text lives only in str(), not in its args."""

    def __str__(self) -> str:
        return "[08004] Too many client tasks"


class MdbConnectionManagerMessageAndNoteContractTests(unittest.TestCase):
    """Second pass: user-facing messages, annotations and shutdown bookkeeping."""

    EXHAUSTED_MESSAGE = (
        "Microsoft Access cannot open another database connection in this OST "
        "Visualizer session. Save any work in other applications, restart OST "
        "Visualizer, and try again."
    )
    UNUSABLE_MESSAGE = (
        "The shared MDB connection is unusable after a cursor cleanup failed, a "
        "connection error or a failed health probe; it is closed when the "
        "outermost lease ends"
    )
    PROBE_MESSAGE = (
        "The shared MDB connection failed its health probe for a nested lease; "
        "it is unusable after a cursor cleanup failed, a connection error or a "
        "failed health probe and is closed when the outermost lease ends"
    )

    def setUp(self) -> None:
        self.connect = _FakeConnect()
        self.connect_patch = patch(
            "ost_visualizer.infrastructure.mdb.connection_manager.pyodbc.connect",
            self.connect,
        )
        self.connect_patch.start()

    def tearDown(self) -> None:
        self.connect_patch.stop()

    def assert_all_resources_released(self) -> None:
        counts = self.connect.counts
        self.assertEqual(counts.connections_opened, counts.connections_closed)
        self.assertEqual(counts.active_connections, 0)
        self.assertEqual(counts.cursors_created, counts.cursors_closed)

    @staticmethod
    def _failing_close(connection, error):
        def close():
            raise error

        connection.close = close

    def test_client_task_exhaustion_message_is_the_exact_user_guidance(self):
        self.connect.max_opens = 0
        manager = MdbConnectionManager()
        with self.assertRaises(DatabaseConnectionUnavailableError) as raised:
            with manager.connection("exhausted-text.mdb"):
                self.fail("lease granted")
        self.assertEqual(str(raised.exception), self.EXHAUSTED_MESSAGE)
        self.assertIsInstance(raised.exception.__cause__, pyodbc.OperationalError)

    def test_maintenance_is_refused_while_writes_are_blocked_and_changes_nothing(self):
        manager = MdbConnectionManager()
        path_key = os.path.normcase(os.path.abspath("blocked-maintenance.mdb"))
        with manager.connection("blocked-maintenance.mdb"):
            pass
        reader = manager._read_conns[path_key]
        manager.set_write_blocked(True)
        with self.assertRaises(WriteBlockedError) as raised:
            with manager.maintenance("blocked-maintenance.mdb"):
                self.fail("maintenance granted while writes are blocked")
        self.assertEqual(
            str(raised.exception),
            "Close On-Screen Takeoff before database maintenance.",
        )
        self.assertEqual(manager._maintenance_paths, set())
        self.assertFalse(reader.closed)
        self.assertIs(manager._read_conns[path_key], reader)
        manager.set_write_blocked(False)
        with manager.maintenance("blocked-maintenance.mdb"):
            self.assertTrue(reader.closed)
        self.assertEqual(manager._maintenance_paths, set())
        manager.close()
        self.assert_all_resources_released()

    def test_maintenance_refusals_and_lease_refusals_carry_exact_messages(self):
        manager = MdbConnectionManager()
        busy = "The database has active operations; try again when they finish."
        with manager.connection("messages.mdb"):
            with self.assertRaises(RuntimeError) as active:
                with manager.maintenance("messages.mdb"):
                    self.fail("maintenance granted under an active lease")
            self.assertEqual(str(active.exception), busy)
            with self.assertRaises(RuntimeError) as mixed:
                with manager.connection("messages.mdb", autocommit=False):
                    self.fail("mixed-mode nested lease granted")
            self.assertEqual(
                str(mixed.exception),
                "Nested MDB connection leases must use the same mode",
            )
        self.assertEqual(manager._maintenance_paths, set())
        with manager.maintenance("messages.mdb"):
            with self.assertRaises(RuntimeError) as overlap:
                with manager.maintenance("messages.mdb"):
                    self.fail("overlapping maintenance granted")
            self.assertEqual(str(overlap.exception), busy)
            with self.assertRaises(RuntimeError) as closed:
                with manager.connection("messages.mdb"):
                    self.fail("lease granted during maintenance")
            self.assertEqual(
                str(closed.exception),
                "The database is temporarily closed for maintenance.",
            )
        manager.set_write_blocked(True)
        with self.assertRaises(WriteBlockedError) as blocked:
            with manager.connection("messages.mdb", autocommit=False):
                self.fail("writer lease granted while writes are blocked")
        self.assertEqual(
            str(blocked.exception), "Database writes are blocked while OST is active"
        )
        self.assertEqual(manager._active_leases, {})
        manager.close()
        self.assert_all_resources_released()

    def test_nested_refusals_on_a_condemned_handle_carry_exact_messages(self):
        manager = MdbConnectionManager()
        with manager.connection("condemned-text.mdb") as outer:
            shared = outer._conn
            with manager.connection("condemned-text.mdb") as inner:
                inner._conn.fail_next_cursor_close = True
                inner.cursor().execute("SELECT")
            with self.assertRaises(RuntimeError) as unusable:
                with manager.connection("condemned-text.mdb"):
                    self.fail("nested lease granted on a condemned handle")
            self.assertEqual(str(unusable.exception), self.UNUSABLE_MESSAGE)
            self.assertFalse(shared.closed)
        self.assertTrue(shared.closed)
        with manager.connection("probe-text.mdb") as outer:
            outer._conn.fail_cursor_open_once = True
            with self.assertRaises(RuntimeError) as probe:
                with manager.connection("probe-text.mdb"):
                    self.fail("nested lease granted on a handle that failed its probe")
            self.assertEqual(str(probe.exception), self.PROBE_MESSAGE)
            self.assertIsInstance(probe.exception.__cause__, pyodbc.OperationalError)
            self.assertEqual(
                probe.exception.__cause__.args, ("HY000", "cursor could not be opened")
            )
        manager.close()
        self.assert_all_resources_released()

    def test_aggregated_close_failures_use_the_documented_group_message(self):
        manager = MdbConnectionManager()
        for path in ("group-a.mdb", "group-b.mdb"):
            with manager.connection(path):
                pass
        errors = [
            pyodbc.OperationalError("HY000", "close a failed"),
            pyodbc.OperationalError("HY000", "close b failed"),
        ]
        handles = list(manager._read_conns.values())
        for handle, error in zip(handles, errors):
            self._failing_close(handle, error)
        with self.assertRaises(ExceptionGroup) as raised:
            manager.close()
        self.assertEqual(raised.exception.message, "Failed to close MDB connections")
        self.assertCountEqual(raised.exception.exceptions, errors)
        for handle in handles:
            del handle.close
        manager.close()
        self.assert_all_resources_released()

    def test_failed_close_after_failed_cursor_cleanup_annotates_the_cursor_error(self):
        captured = []
        original_close_cursors = ConnectionWrapper.close_cursors

        def spying_close_cursors(wrapper):
            errors = original_close_cursors(wrapper)
            captured.append(errors)
            return errors

        manager = MdbConnectionManager()
        with patch.object(ConnectionWrapper, "close_cursors", spying_close_cursors):
            with manager.connection("annotated.mdb") as lease:
                first = lease._conn
                self._failing_close(
                    first, pyodbc.OperationalError("HY000", "connection close failed")
                )
                first.fail_next_cursor_close = True
                lease.cursor().execute("SELECT")
        # The lease itself succeeded; the swallowed cleanup error carries the note.
        self.assertEqual(len(captured), 1)
        self.assertEqual(len(captured[0]), 1)
        self.assertEqual(
            captured[0][0].__notes__,
            [
                "The MDB connection with an unclosed cursor could not be closed: "
                "('HY000', 'connection close failed')"
            ],
        )
        self.assertFalse(first.closed)
        del first.close
        # Positive control: a close that works leaves the cleanup error unannotated.
        captured.clear()
        with patch.object(ConnectionWrapper, "close_cursors", spying_close_cursors):
            with manager.connection("annotated.mdb") as lease:
                lease._conn.fail_next_cursor_close = True
                lease.cursor().execute("SELECT")
        self.assertEqual(len(captured[0]), 1)
        self.assertFalse(hasattr(captured[0][0], "__notes__"))
        manager.close()
        self.assert_all_resources_released()

    def test_shutdown_discards_health_flags_of_handles_no_longer_owned(self):
        manager = MdbConnectionManager()
        with manager.connection("flag-reset.mdb"):
            pass
        manager._unhealthy_connection_ids.update({111, 222})
        manager.close()
        self.assertEqual(manager._unhealthy_connection_ids, set())
        self.assertEqual(manager._read_conns, {})
        self.assert_all_resources_released()

    def test_connection_error_after_the_handle_was_closed_by_someone_else_flags_nothing(
        self,
    ):
        for replaced in (False, True):
            with self.subTest(replaced_by_a_new_handle=replaced):
                self.connect.counts = _LifecycleCounts()
                manager = MdbConnectionManager()
                path_key = os.path.normcase(os.path.abspath("unowned-outer.mdb"))
                replacement = None
                with self.assertRaisesRegex(pyodbc.OperationalError, "communication"):
                    with manager.connection("unowned-outer.mdb") as lease:
                        shared = lease._conn
                        manager.close_database("unowned-outer.mdb")
                        self.assertTrue(shared.closed)
                        if replaced:
                            with manager.connection("unowned-outer.mdb") as nested:
                                replacement = nested._conn
                        raise pyodbc.OperationalError("08S01", "communication link")
                self.assertEqual(manager._unhealthy_connection_ids, set())
                self.assertEqual(manager._deferred_eviction_ids, set())
                self.assertEqual(manager._active_leases, {})
                if replaced:
                    # The error concerned the old handle only: the replacement
                    # opened meanwhile stays open, owned and unflagged.
                    self.assertFalse(replacement.closed)
                    self.assertIs(manager._read_conns[path_key], replacement)
                else:
                    self.assertEqual(manager._read_conns, {})
                manager.close()
                self.assert_all_resources_released()

    def test_client_task_exhaustion_text_is_matched_across_args_and_str(self):
        split_args = pyodbc.OperationalError("08004", "Too many", "client tasks")
        self.assertIs(MdbConnectionManager._is_client_task_exhaustion(split_args), True)
        self.assertIs(
            MdbConnectionManager._is_client_task_exhaustion(
                _TextOnlyExhaustionError("opaque")
            ),
            True,
        )
        for negative in (
            pyodbc.OperationalError("08004", "Too many", "tasks"),
            pyodbc.OperationalError("HY000", "Too many client tasks"),
            pyodbc.OperationalError("08004"),
        ):
            with self.subTest(negative=negative.args):
                self.assertIs(
                    MdbConnectionManager._is_client_task_exhaustion(negative), False
                )

    def test_replacement_check_returns_a_strict_boolean_for_each_signal(self):
        healthy = Mock()
        dead = Mock()
        dead.cursor.side_effect = pyodbc.OperationalError("HY000", "gone")
        check = MdbConnectionManager._connection_requires_replacement
        self.assertIs(check(healthy, pyodbc.OperationalError("HY000", "x")), False)
        healthy.cursor.return_value.close.assert_called_once_with()
        self.assertIs(check(healthy, pyodbc.OperationalError(" 08s01 ", "x")), True)
        self.assertIs(check(dead, pyodbc.OperationalError("HY000", "x")), True)
        self.assertIs(check(healthy, pyodbc.OperationalError("HY000")), False)


class MdbConnectionManagerConnectContractTests(unittest.TestCase):
    """Third pass: what is handed to the ODBC driver, lease-mode safety,
    per-database independence and close-error continuation."""

    DRIVER = "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"

    def setUp(self) -> None:
        self.connect = _FakeConnect()
        patcher = patch(
            "ost_visualizer.infrastructure.mdb.connection_manager.pyodbc.connect",
            self.connect,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _failing_close(connection):
        """Make close() raise until state['fail'] is cleared; count the attempts."""
        original = connection.close
        state = {"fail": True, "attempts": 0}

        def close():
            state["attempts"] += 1
            if state["fail"]:
                raise pyodbc.OperationalError("HY000", "close failed")
            original()

        connection.close = close
        return state

    def test_the_driver_gets_the_absolute_normalized_path_and_the_lease_mode(self):
        manager = MdbConnectionManager()
        spelling = "Rel\\..\\Conn.MDB"
        key = os.path.normcase(os.path.abspath(spelling))
        self.assertTrue(os.path.isabs(key))
        with manager.connection(spelling) as reader:
            read_handle = reader._conn
        with manager.connection(spelling, autocommit=False) as writer:
            write_handle = writer._conn
        expected = self.DRIVER + f"DBQ={key};"
        self.assertEqual(read_handle.connection_string, expected)
        self.assertEqual(write_handle.connection_string, expected)
        self.assertIs(read_handle.autocommit, True)
        self.assertIs(write_handle.autocommit, False)
        self.assertEqual(self.connect.connect_attempts, 2)
        manager.close()

    def test_a_read_lease_nested_in_a_write_lease_is_refused_and_keeps_pending_work(
        self,
    ):
        manager = MdbConnectionManager()
        key = os.path.normcase(os.path.abspath("nest-wr.mdb"))
        with manager.connection("nest-wr.mdb", autocommit=False) as outer:
            outer.cursor().execute("INSERT_PENDING")
            writer = outer._conn
            self.assertEqual(writer.pending_rows, ["pending"])
            with self.assertRaises(RuntimeError) as refused:
                with manager.connection("nest-wr.mdb"):
                    self.fail("read lease granted inside a write lease")
            self.assertEqual(
                str(refused.exception),
                "Nested MDB connection leases must use the same mode",
            )
            self.assertEqual(writer.pending_rows, ["pending"])
            self.assertEqual(self.connect.counts.rollbacks, 0)
            self.assertEqual(manager._active_leases, {key: (False, 1)})
        self.assertEqual(self.connect.counts.rollbacks, 0)
        self.assertFalse(writer.closed)
        manager.close()

    def test_leases_on_different_databases_do_not_block_each_other(self):
        manager = MdbConnectionManager()
        first_in = threading.Event()
        second_in = threading.Event()
        release_first = threading.Event()

        def first() -> None:
            with manager.connection("a.mdb"):
                first_in.set()
                release_first.wait(timeout=30.0)

        def second() -> None:
            with manager.connection("b.mdb"):
                second_in.set()

        holder = threading.Thread(target=first)
        other = threading.Thread(target=second)
        holder.start()
        try:
            self.assertTrue(first_in.wait(timeout=5.0))
            other.start()
            entered = second_in.wait(timeout=5.0)
        finally:
            release_first.set()
            holder.join()
        other.join()
        self.assertTrue(entered, "a lease on b.mdb waited for the lease on a.mdb")
        manager.close()

    def test_close_database_still_closes_the_write_pool_after_the_read_pool_fails(
        self,
    ):
        manager = MdbConnectionManager()
        with manager.connection("both.mdb"):
            pass
        with manager.connection("both.mdb", autocommit=False):
            pass
        (reader,) = manager._read_conns.values()
        (writer,) = manager._write_conns.values()
        read_state = self._failing_close(reader)
        write_state = self._failing_close(writer)
        with self.assertRaises(ExceptionGroup) as raised:
            manager.close_database("both.mdb")
        self.assertEqual(len(raised.exception.exceptions), 2)
        self.assertEqual((read_state["attempts"], write_state["attempts"]), (1, 1))
        self.assertEqual(len(manager._read_conns), 1)
        self.assertEqual(len(manager._write_conns), 1)
        read_state["fail"] = write_state["fail"] = False
        manager.close()
        self.assertEqual(self.connect.counts.active_connections, 0)

    def test_close_database_with_only_the_read_pool_failing_closes_the_writer(self):
        manager = MdbConnectionManager()
        with manager.connection("one.mdb"):
            pass
        with manager.connection("one.mdb", autocommit=False):
            pass
        (reader,) = manager._read_conns.values()
        (writer,) = manager._write_conns.values()
        read_state = self._failing_close(reader)
        with self.assertRaises(pyodbc.OperationalError):
            manager.close_database("one.mdb")
        self.assertTrue(writer.closed)
        self.assertEqual(manager._write_conns, {})
        self.assertEqual(len(manager._read_conns), 1)
        read_state["fail"] = False
        manager.close()
        self.assertEqual(self.connect.counts.active_connections, 0)

    def test_shutdown_attempts_every_database_when_each_one_fails_in_both_pools(self):
        manager = MdbConnectionManager()
        paths = ("p0.mdb", "p1.mdb", "p2.mdb")
        for path in paths:
            with manager.connection(path):
                pass
            with manager.connection(path, autocommit=False):
                pass
        states = [
            self._failing_close(handle)
            for pool in (manager._read_conns, manager._write_conns)
            for handle in pool.values()
        ]
        self.assertEqual(len(states), 6)
        with self.assertRaises(ExceptionGroup) as raised:
            manager.close()
        self.assertEqual(raised.exception.message, "Failed to close MDB connections")
        self.assertEqual(len(raised.exception.exceptions), 3)
        for per_database in raised.exception.exceptions:
            self.assertIsInstance(per_database, ExceptionGroup)
            self.assertEqual(len(per_database.exceptions), 2)
        self.assertEqual([state["attempts"] for state in states], [1] * 6)
        self.assertEqual(len(manager._read_conns), 3)
        self.assertEqual(len(manager._write_conns), 3)
        for state in states:
            state["fail"] = False
        manager.close()
        self.assertEqual(self.connect.counts.active_connections, 0)

    def test_lifting_the_write_block_keeps_cached_writer_handles(self):
        manager = MdbConnectionManager()
        key = os.path.normcase(os.path.abspath("keep.mdb"))
        with manager.connection("keep.mdb", autocommit=False) as lease:
            writer = lease._conn
        manager.set_write_blocked(False)
        self.assertFalse(manager.is_write_blocked())
        self.assertFalse(writer.closed)
        self.assertIs(manager._write_conns[key], writer)
        with manager.connection("keep.mdb", autocommit=False) as again:
            self.assertIs(again._conn, writer)
        self.assertEqual(self.connect.counts.connections_opened, 1)
        manager.close()

    def test_only_sqlstate_class_08_marks_the_connection_for_replacement(self):
        healthy = Mock()
        check = MdbConnectionManager._connection_requires_replacement
        for state in ("07002", "01000", "42S02", "HY008", "28000", "0"):
            with self.subTest(state=state):
                self.assertIs(
                    check(healthy, pyodbc.OperationalError(state, "x")), False
                )
        for state in ("08001", "08S01", "08004"):
            with self.subTest(state=state):
                self.assertIs(check(healthy, pyodbc.OperationalError(state, "x")), True)

    def test_exhaustion_needs_the_08004_state_not_just_a_connection_class_marker(
        self,
    ):
        check = MdbConnectionManager._is_client_task_exhaustion
        for state, text in (
            ("08001", "-1036"),
            ("08S01", "Too many client tasks"),
            ("HY000", "x 08 -1036"),
        ):
            with self.subTest(state=state):
                self.assertIs(check(pyodbc.OperationalError(state, text)), False)
        self.assertIs(check(pyodbc.OperationalError("08004", "-1036")), True)
        self.assertIs(
            check(pyodbc.OperationalError("08004", "Too many client tasks")), True
        )


class _RecordingRawCursor:
    def __init__(self, *, close_error=None):
        self.calls = []
        self.close_error = close_error
        self.description = (("UID", None),)
        self.rowcount = -1
        self.next_set = 1

    def execute(self, *args, **kwargs):
        self.calls.append(("execute", args, kwargs))

    def columns(self, *args, **kwargs):
        self.calls.append(("columns", args, kwargs))

    def tables(self, *args, **kwargs):
        self.calls.append(("tables", args, kwargs))

    def fetchone(self):
        return ("one",)

    def fetchall(self):
        return [("all",)]

    def nextset(self):
        return self.next_set

    def close(self):
        self.calls.append(("close", (), {}))
        if self.close_error is not None:
            raise self.close_error


class _RecordingRawConnection:
    def __init__(self, cursors=(), *, rollback_error=None):
        self._cursors = list(cursors)
        self.cursor_calls = []
        self.events = []
        self.rollback_error = rollback_error

    def cursor(self, *args, **kwargs):
        self.cursor_calls.append((args, kwargs))
        return self._cursors.pop(0) if self._cursors else _RecordingRawCursor()

    def commit(self):
        self.events.append("commit")

    def rollback(self):
        self.events.append("rollback")
        if self.rollback_error is not None:
            raise self.rollback_error

    def getinfo(self, info_type):
        return ("info", info_type)


class ConnectionWrapperContractTests(unittest.TestCase):
    """Second pass: the managed Access connection/cursor lease contract."""

    def test_cursor_lease_forwards_statements_results_and_metadata(self):
        raw_cursor = _RecordingRawCursor()
        wrapper = ConnectionWrapper(_RecordingRawConnection([raw_cursor]))
        with wrapper.cursor() as cursor:
            self.assertIs(cursor.execute("SELECT ?", 5, timeout=2), cursor)
            self.assertIs(cursor.columns(table="T"), cursor)
            self.assertIs(cursor.tables(tableType="TABLE"), cursor)
            self.assertEqual(cursor.fetchone(), ("one",))
            self.assertEqual(cursor.fetchall(), [("all",)])
            self.assertIs(cursor.nextset(), True)
            raw_cursor.next_set = None
            self.assertIs(cursor.nextset(), False)
            self.assertEqual(cursor.description, (("UID", None),))
            self.assertEqual(cursor.rowcount, -1)
            self.assertIs(cursor.connection, wrapper)
        self.assertEqual(
            raw_cursor.calls,
            [
                ("execute", ("SELECT ?", 5), {"timeout": 2}),
                ("columns", (), {"table": "T"}),
                ("tables", (), {"tableType": "TABLE"}),
                ("close", (), {}),
            ],
        )

    def test_connection_forwards_commit_rollback_and_driver_info(self):
        raw = _RecordingRawConnection()
        wrapper = ConnectionWrapper(raw)
        wrapper.commit()
        wrapper.rollback()
        self.assertEqual(raw.events, ["commit", "rollback"])
        self.assertFalse(wrapper.rollback_failed)
        self.assertEqual(wrapper.getinfo(7), ("info", 7))

    def test_closing_a_cursor_unregisters_it_once_even_when_the_driver_fails(self):
        failing = _RecordingRawCursor(close_error=pyodbc.OperationalError("HY000", "x"))
        healthy = _RecordingRawCursor()
        wrapper = ConnectionWrapper(_RecordingRawConnection([failing, healthy]))
        first = wrapper.cursor()
        second = wrapper.cursor()
        self.assertEqual(wrapper._open_cursors, [first, second])
        with self.assertRaises(pyodbc.OperationalError):
            first.close()
        self.assertEqual(wrapper._open_cursors, [second])
        first.close()
        self.assertEqual(
            [call for call in failing.calls if call[0] == "close"], [("close", (), {})]
        )
        second.close()
        second.close()
        self.assertEqual(wrapper._open_cursors, [])
        self.assertEqual(
            [call for call in healthy.calls if call[0] == "close"], [("close", (), {})]
        )

    def test_close_cursors_closes_every_open_cursor_and_returns_the_failures(self):
        errors = [
            pyodbc.OperationalError("HY000", "first"),
            pyodbc.OperationalError("HY000", "third"),
        ]
        raw_cursors = [
            _RecordingRawCursor(close_error=errors[0]),
            _RecordingRawCursor(),
            _RecordingRawCursor(close_error=errors[1]),
        ]
        wrapper = ConnectionWrapper(_RecordingRawConnection(raw_cursors))
        for _index in raw_cursors:
            wrapper.cursor()
        self.assertEqual(wrapper.close_cursors(), errors)
        self.assertEqual(wrapper._open_cursors, [])
        for raw_cursor in raw_cursors:
            self.assertEqual([call[0] for call in raw_cursor.calls], ["close"])
        self.assertEqual(wrapper.close_cursors(), [])

    def test_cursor_options_are_forwarded_unless_the_driver_rejects_them(self):
        raw = _RecordingRawConnection()
        wrapper = ConnectionWrapper(raw)
        wrapper.cursor()
        wrapper.cursor(1, scrollable=True)
        self.assertEqual(raw.cursor_calls, [((), {}), ((1,), {"scrollable": True})])
        strict_raw = _RecordingRawConnection()
        strict = ConnectionWrapper(strict_raw, accepts_cursor_options=False)
        strict.cursor()
        self.assertEqual(strict_raw.cursor_calls, [((), {})])
        for args, kwargs in (((1,), {}), ((), {"scrollable": True})):
            with self.subTest(args=args, kwargs=kwargs):
                with self.assertRaises(TypeError) as refused:
                    strict.cursor(*args, **kwargs)
                self.assertEqual(
                    str(refused.exception),
                    "This database cursor does not accept cursor options",
                )
        self.assertEqual(strict_raw.cursor_calls, [((), {})])
        self.assertEqual(len(strict._open_cursors), 1)

    def test_only_a_failed_driver_rollback_marks_the_wrapper(self):
        failure = pyodbc.OperationalError("HY000", "rollback refused")
        wrapper = ConnectionWrapper(_RecordingRawConnection(rollback_error=failure))
        with self.assertRaises(pyodbc.OperationalError) as raised:
            wrapper.rollback()
        self.assertIs(raised.exception, failure)
        self.assertTrue(wrapper.rollback_failed)
        foreign = ConnectionWrapper(
            _RecordingRawConnection(rollback_error=RuntimeError("not the driver"))
        )
        with self.assertRaises(RuntimeError):
            foreign.rollback()
        self.assertFalse(foreign.rollback_failed)

    def test_a_rollback_interrupted_by_any_baseexception_marks_the_wrapper(self):
        for exception_type in (KeyboardInterrupt, SystemExit, _Abort):
            with self.subTest(exception=exception_type.__name__):
                interrupt = exception_type()
                wrapper = ConnectionWrapper(
                    _RecordingRawConnection(rollback_error=interrupt)
                )
                with self.assertRaises(exception_type) as raised:
                    wrapper.rollback()
                self.assertIs(raised.exception, interrupt)
                self.assertTrue(wrapper.rollback_failed)


_MANAGER_MODULE = "ost_visualizer.infrastructure.mdb.connection_manager"


class _OwnedLock:
    """A non-reentrant mutex that knows which thread holds it."""

    def __init__(self) -> None:
        self._mutex = threading.Lock()
        self.owner = None

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        acquired = self._mutex.acquire(blocking, timeout)
        if acquired:
            self.owner = threading.get_ident()
        return acquired

    def release(self) -> None:
        self.owner = None
        self._mutex.release()

    def __enter__(self) -> "_OwnedLock":
        self.acquire()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.release()

    def held(self) -> bool:
        return self.owner == threading.get_ident()


class _ContendedRLock:
    """A re-entrant lock that announces when a thread finds it held by another
    thread, just before that thread blocks on it. This turns "the second thread
    is waiting for the first" into an event instead of a timed guess."""

    def __init__(self) -> None:
        self._rlock = threading.RLock()
        self.contended = threading.Event()

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        if self._rlock.acquire(False):
            return True
        self.contended.set()
        return self._rlock.acquire(blocking, timeout)

    def release(self) -> None:
        self._rlock.release()

    def __enter__(self) -> "_ContendedRLock":
        self.acquire()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.release()


class _LockAudit:
    """Records every access made by the manager's own code to state that the
    manager lock guards while that lock is not held by the accessing thread.
    Accesses from the test module itself are ignored (they inspect state)."""

    def __init__(self) -> None:
        self.lock = _OwnedLock()
        self.violations = []
        self.observed = 0
        self.structures = set()
        self.driver_calls = set()

    def check(self, structure: str, operation: str) -> None:
        # Frame 0 is this method, 1 the audited operation, 2 its caller.
        frame = sys._getframe(2)
        if frame.f_globals.get("__name__") != _MANAGER_MODULE:
            return
        self.observed += 1
        self.structures.add(structure)
        if not self.lock.held():
            self.violations.append(
                f"{structure}.{operation} used by {frame.f_code.co_name} "
                f"(line {frame.f_lineno}) without the manager lock"
            )


_NOT_AUDITED = frozenset(
    {
        "__class__",
        "__init__",
        "__new__",
        "__getattribute__",
        "__setattr__",
        "__delattr__",
        "__init_subclass__",
        "__subclasshook__",
        "__reduce__",
        "__reduce_ex__",
        "__sizeof__",
        "__dir__",
        "__format__",
        "__repr__",
        "__str__",
        "__hash__",
        "__getstate__",
        "__class_getitem__",
        "fromkeys",
    }
)


def _audit_every_operation(proxy_class: type, base: type) -> None:
    """Give proxy_class an audited override of every callable member of base
    (methods and operator dunders), so no way of touching the container escapes
    the audit. Each override checks first and then delegates to base."""
    for name in dir(base):
        member = getattr(base, name)
        if name in _NOT_AUDITED or not callable(member):
            continue

        def audited(self, *args, _member=member, _name=name, **kwargs):
            self._audit.check(self._label, _name)
            return _member(self, *args, **kwargs)

        audited.__name__ = name
        setattr(proxy_class, name, audited)


class _GuardedDict(dict):
    def __init__(self, audit: _LockAudit, label: str, items) -> None:
        super().__init__(items)
        self._audit = audit
        self._label = label


class _GuardedSet(set):
    def __init__(self, audit: _LockAudit, label: str, items) -> None:
        super().__init__(items)
        self._audit = audit
        self._label = label


_audit_every_operation(_GuardedDict, dict)
_audit_every_operation(_GuardedSet, set)


class _AuditedManager(MdbConnectionManager):
    """The real manager with its lock and shared containers instrumented."""

    _DICTS = ("_read_conns", "_write_conns", "_path_locks", "_active_leases")
    _SETS = (
        "_unhealthy_connection_ids",
        "_deferred_eviction_ids",
        "_writer_read_paths",
        "_maintenance_paths",
    )

    def __init__(self) -> None:
        super().__init__()
        self.audit = _LockAudit()
        self._lock = self.audit.lock
        for name in self._DICTS:
            setattr(self, name, _GuardedDict(self.audit, name, getattr(self, name)))
        for name in self._SETS:
            setattr(self, name, _GuardedSet(self.audit, name, getattr(self, name)))

    def audit_driver_call(self, what: str, connection_string: str) -> None:
        self.audit.driver_calls.add(what)
        key = connection_string.split("DBQ=", 1)[1].rstrip(";")
        path_lock = dict.get(self._path_locks, key)
        if not self.audit.lock.held():
            self.audit.violations.append(f"driver {what} without the manager lock")
        if path_lock is None or not path_lock._is_owned():
            self.audit.violations.append(f"driver {what} without the database lock")

    @property
    def _write_blocked(self) -> bool:
        audit = self.__dict__.get("audit")
        if audit is not None:
            audit.check("_write_blocked", "read")
        return self.__dict__["_write_blocked_value"]

    @_write_blocked.setter
    def _write_blocked(self, blocked: bool) -> None:
        audit = self.__dict__.get("audit")
        if audit is not None:
            audit.check("_write_blocked", "write")
        self.__dict__["_write_blocked_value"] = blocked


class _AuditedConnection(_FakeConnection):
    def __init__(self, manager, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._manager = manager

    def close(self) -> None:
        self._manager_driver_call("close")
        super().close()

    def _manager_driver_call(self, what: str) -> None:
        self._manager.audit_driver_call(what, self.connection_string)


class _AuditedConnect(_FakeConnect):
    """pyodbc.connect fake that checks, at the moment the driver is called,
    that the caller holds the manager lock and the lock of that database."""

    def __init__(self) -> None:
        super().__init__()
        self.manager = None

    def __call__(self, connection_string: str, *, autocommit: bool):
        self.manager.audit_driver_call("connect", connection_string)
        self.connect_attempts += 1
        if (
            self.max_opens is not None
            and self.counts.connections_opened >= self.max_opens
        ):
            raise pyodbc.OperationalError(
                "08004", "Too many client tasks. (-1036) (SQLDriverConnect)"
            )
        return _AuditedConnection(
            self.manager, self.counts, connection_string, autocommit
        )


class MdbConnectionManagerLockDisciplineTests(unittest.TestCase):
    """Concurrency pass: the lock discipline is checked directly. Removing a lock
    never fails a single-threaded test, so the manager's own code is audited for
    every access to guarded state and every driver call, and the cross-thread
    waits are observed as events (no sleeps)."""

    def setUp(self) -> None:
        self.connect = _AuditedConnect()
        patcher = patch(
            "ost_visualizer.infrastructure.mdb.connection_manager.pyodbc.connect",
            self.connect,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _audited_manager(self) -> _AuditedManager:
        manager = _AuditedManager()
        self.connect.manager = manager
        return manager

    def test_the_audit_flags_unlocked_use_from_the_manager_module_only(self):
        manager = self._audited_manager()
        manager._read_conns["probe"] = object()
        self.assertIn("probe", manager._read_conns)
        self.assertEqual(manager.audit.violations, [])
        unlocked = compile("manager._read_conns.get('probe')", "<m>", "eval")
        eval(unlocked, {"__name__": _MANAGER_MODULE, "manager": manager})
        with manager._lock:
            eval(unlocked, {"__name__": _MANAGER_MODULE, "manager": manager})
        self.assertEqual(len(manager.audit.violations), 1)
        self.assertEqual(manager.audit.observed, 2)

    def test_all_guarded_state_and_driver_calls_stay_under_the_documented_locks(self):
        manager = self._audited_manager()
        writer = MdbWriter(conn_manager=manager)
        failure = pyodbc.OperationalError("HY000", "rollback refused")
        # Plain, nested, writer and borrowed-writer leases.
        with manager.connection("audit.mdb"):
            with manager.connection("audit.mdb"):
                pass
            with self.assertRaises(RuntimeError):
                with manager.connection("audit.mdb", autocommit=False):
                    pass
        with writer._connection("audit.mdb") as lease:
            lease.cursor().execute("INSERT_PENDING")
        with manager.connection("audit.mdb"):
            pass
        # Connection error, statement error and failed rollback evictions.
        with self.assertRaises(pyodbc.OperationalError):
            with manager.connection("audit.mdb") as lease:
                lease.cursor().execute("RAISE_CONNECTION_CLASS_ERROR")
        with self.assertRaises(pyodbc.ProgrammingError):
            with manager.connection("audit.mdb") as lease:
                lease.cursor().execute("RAISE_SCHEMA_ERROR")
        with writer._connection("audit.mdb"):
            pass
        with self.assertRaises(pyodbc.OperationalError):
            with manager.connection("audit.mdb") as lease:
                lease._conn.rollback_error = failure
        # Cursor-cleanup failure under a nested lease (deferred close), a
        # failed idle probe and a condemned nested lease.
        with manager.connection("audit.mdb") as outer:
            with manager.connection("audit.mdb") as inner:
                inner._conn.fail_next_cursor_close = True
                inner.cursor().execute("SELECT")
            with self.assertRaises(RuntimeError):
                with manager.connection("audit.mdb"):
                    pass
        with manager.connection("audit.mdb") as lease:
            lease._conn.unhealthy = True
        with manager.connection("audit.mdb"):
            pass
        # Preferences, write blocking and maintenance.
        manager.use_committed_writer_for_reads("audit.mdb")
        manager.set_write_blocked(True)
        self.assertTrue(manager.is_write_blocked())
        with self.assertRaises(WriteBlockedError):
            with manager.connection("audit.mdb", autocommit=False):
                pass
        with self.assertRaises(WriteBlockedError):
            with manager.maintenance("audit.mdb"):
                pass
        manager.set_write_blocked(False)
        self.assertFalse(manager.is_write_blocked())
        with manager.maintenance("audit.mdb"):
            with self.assertRaises(RuntimeError):
                with manager.connection("audit.mdb"):
                    pass
            with self.assertRaises(RuntimeError):
                with manager.maintenance("audit.mdb"):
                    pass
        with manager.connection("audit.mdb"):
            with self.assertRaises(RuntimeError):
                with manager.maintenance("audit.mdb"):
                    pass
        # Pool teardown, including a close that fails and is retried.
        with writer._connection("audit.mdb"):
            pass
        manager.close_write_connections()
        with writer._connection("audit.mdb"):
            pass
        manager.close_database("audit.mdb")
        with manager.connection("audit.mdb") as lease:
            handle = lease._conn
        original_close = handle.close
        handle.close = Mock(side_effect=pyodbc.OperationalError("HY000", "stuck"))
        with self.assertRaises(pyodbc.OperationalError):
            manager.close()
        handle.close = original_close
        self.connect.max_opens = self.connect.counts.connections_opened
        with self.assertRaises(DatabaseConnectionUnavailableError):
            with manager.connection("other.mdb"):
                pass
        manager.close()
        self.assertEqual(manager.audit.violations, [])
        # The audit really looked: every guarded structure was touched by the
        # manager's own code, and the driver was called to connect and to close.
        self.assertGreater(manager.audit.observed, 0)
        expected = set(_AuditedManager._DICTS) | set(_AuditedManager._SETS)
        expected.add("_write_blocked")
        self.assertEqual(expected - manager.audit.structures, set())
        self.assertEqual({"connect", "close"} - manager.audit.driver_calls, set())
        self.assertEqual(self.connect.counts.active_connections, 0)


class MdbConnectionManagerCrossThreadWaitTests(unittest.TestCase):
    """Concurrency pass: maintenance-style calls from another thread wait for the
    lease holding the database lock. The wait is an event announced by the lock
    itself (a thread that found it held), so nothing here sleeps or guesses."""

    def setUp(self) -> None:
        self.connect = _FakeConnect()
        patcher = patch(
            "ost_visualizer.infrastructure.mdb.connection_manager.pyodbc.connect",
            self.connect,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _hold_lease_on_another_thread(self, manager, path, **lease_options):
        held = threading.Event()
        release = threading.Event()
        handles = []

        def hold() -> None:
            with manager.connection(path, **lease_options) as lease:
                handles.append(lease._conn)
                held.set()
                release.wait(timeout=10.0)

        holder = threading.Thread(target=hold, daemon=True)
        holder.start()
        self.assertTrue(held.wait(timeout=5.0))
        return holder, release, handles[0]

    def _run_while_a_lease_is_held(self, action, **lease_options):
        """Run action(manager, path) on a second thread while the first holds a
        lease. Returns (manager, handle, snapshot taken while the second thread
        was provably waiting, finished flag)."""
        manager = MdbConnectionManager()
        path = "contended.mdb"
        key = os.path.normcase(os.path.abspath(path))
        lock = _ContendedRLock()
        manager._path_locks[key] = lock
        holder, release, handle = self._hold_lease_on_another_thread(
            manager, path, **lease_options
        )
        finished = threading.Event()

        def run_action() -> None:
            action(manager, path)
            finished.set()

        worker = threading.Thread(target=run_action, daemon=True)
        try:
            worker.start()
            self.assertTrue(
                lock.contended.wait(timeout=3.0),
                "the second thread never waited for the database lock",
            )
            waiting = (handle.closed, finished.is_set())
        finally:
            release.set()
            holder.join(timeout=10.0)
            worker.join(timeout=10.0)
        self.assertFalse(holder.is_alive() or worker.is_alive())
        return manager, key, handle, waiting, finished

    def test_close_database_waits_for_the_lease_held_by_another_thread(self):
        manager, key, handle, waiting, finished = self._run_while_a_lease_is_held(
            lambda manager, path: manager.close_database(path)
        )
        self.assertEqual(waiting, (False, False))
        self.assertTrue(finished.is_set())
        self.assertTrue(handle.closed)
        self.assertEqual(manager._read_conns, {})

    def test_close_write_connections_waits_for_a_write_lease_held_elsewhere(self):
        manager, key, handle, waiting, finished = self._run_while_a_lease_is_held(
            lambda manager, path: manager.close_write_connections(),
            autocommit=False,
        )
        self.assertEqual(waiting, (False, False))
        self.assertTrue(finished.is_set())
        self.assertTrue(handle.closed)
        self.assertEqual(manager._write_conns, {})

    def test_the_writer_read_preference_waits_for_the_lease_and_is_then_applied(self):
        manager, key, handle, waiting, finished = self._run_while_a_lease_is_held(
            lambda manager, path: manager.use_committed_writer_for_reads(path)
        )
        self.assertEqual(waiting, (False, False))
        self.assertTrue(finished.is_set())
        self.assertIn(key, manager._writer_read_paths)
        self.assertFalse(handle.closed)
        manager.close()


class MdbConnectionManagerPoolOwnershipTests(unittest.TestCase):
    """Concurrency pass: exception paths and re-pooling must leave the pool and
    the lease bookkeeping consistent, and never act on a handle that the pool
    no longer owns."""

    def setUp(self) -> None:
        self.connect = _FakeConnect()
        patcher = patch(
            "ost_visualizer.infrastructure.mdb.connection_manager.pyodbc.connect",
            self.connect,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_close_leaves_a_replacement_the_pool_acquired_during_the_close(self):
        manager = MdbConnectionManager()
        with manager.connection("swap.mdb"):
            pass
        key = os.path.normcase(os.path.abspath("swap.mdb"))
        old = manager._read_conns[key]
        replacement = _FakeConnection(self.connect.counts, "replacement", True)
        manager._unhealthy_connection_ids.add(id(old))
        original_close = old.close

        def close_while_the_path_is_repooled() -> None:
            manager._read_conns[key] = replacement
            original_close()

        old.close = close_while_the_path_is_repooled
        manager.close_database("swap.mdb")
        self.assertTrue(old.closed)
        self.assertIs(manager._read_conns[key], replacement)
        self.assertFalse(replacement.closed)
        # The closed handle's health flag goes with it either way.
        self.assertNotIn(id(old), manager._unhealthy_connection_ids)
        replacement.close()
        manager._read_conns.clear()

    def test_deferred_close_never_touches_a_handle_pooled_after_the_condemned_one(self):
        manager = MdbConnectionManager()
        key = os.path.normcase(os.path.abspath("repool.mdb"))
        with manager.connection("repool.mdb") as outer:
            condemned = outer._conn
            with manager.connection("repool.mdb") as inner:
                inner._conn.fail_next_cursor_close = True
                inner.cursor().execute("SELECT")
            self.assertEqual(manager._deferred_eviction_ids, {id(condemned)})
            # The condemned handle is closed for good under the outer lease and
            # a fresh one is pooled for the same path before the lease ends.
            manager.close_database("repool.mdb")
            self.assertTrue(condemned.closed)
            with manager.connection("repool.mdb") as again:
                replacement = again._conn
            self.assertIsNot(replacement, condemned)
        self.assertFalse(replacement.closed)
        self.assertIs(manager._read_conns[key], replacement)
        self.assertEqual(manager._deferred_eviction_ids, set())
        self.assertEqual(manager._unhealthy_connection_ids, set())
        self.assertEqual(manager._active_leases, {})
        manager.close()
        self.assertEqual(self.connect.counts.active_connections, 0)

    def test_an_unexpected_cursor_cleanup_failure_leaves_the_lease_bookkeeping_clean(
        self,
    ):
        manager = MdbConnectionManager()
        with patch.object(
            ConnectionWrapper,
            "close_cursors",
            side_effect=RuntimeError("cleanup exploded"),
        ):
            with self.assertRaisesRegex(RuntimeError, "cleanup exploded"):
                with manager.connection("explode.mdb"):
                    pass
        self.assertEqual(manager._active_leases, {})
        self.assertEqual(manager._deferred_eviction_ids, set())
        with manager.connection("explode.mdb") as lease:
            lease.cursor().execute("SELECT")
        self.assertEqual(self.connect.counts.connections_opened, 1)
        manager.close()
        self.assertEqual(self.connect.counts.active_connections, 0)

    def test_a_dead_cached_writer_is_replaced_in_the_write_pool_not_the_read_pool(
        self,
    ):
        manager = MdbConnectionManager()
        path = "dead-writer.mdb"
        key = os.path.normcase(os.path.abspath(path))
        with manager.connection(path):
            pass
        with manager.connection(path, autocommit=False):
            pass
        manager.use_committed_writer_for_reads(path)
        reader = manager._read_conns[key]
        dead_writer = manager._write_conns[key]
        dead_writer.unhealthy = True
        with manager.connection(path, autocommit=False) as lease:
            new_writer = lease._conn
        self.assertIsNot(new_writer, dead_writer)
        self.assertTrue(dead_writer.closed)
        self.assertIs(manager._write_conns[key], new_writer)
        self.assertIs(manager._read_conns[key], reader)
        self.assertFalse(reader.closed)
        self.assertIs(new_writer.autocommit, False)
        # Only a borrowed writer drops the reader preference with the handle.
        self.assertIn(key, manager._writer_read_paths)
        manager.close()
        self.assertEqual(self.connect.counts.active_connections, 0)

    def test_a_reader_opened_after_the_writer_was_lost_is_not_rolled_back_as_borrowed(
        self,
    ):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        path = "writer-lost-plain.mdb"
        key = os.path.normcase(os.path.abspath(path))
        with writer._connection(path):
            pass
        self.assertIn(key, manager._writer_read_paths)
        manager.close_write_connections()
        rollbacks = self.connect.counts.rollbacks
        with manager.connection(path) as lease:
            fresh_reader = lease._conn
        # Only a borrowed writer is rolled back at the end of a read lease; the
        # reader that replaced the lost writer is a plain read handle.
        self.assertEqual(self.connect.counts.rollbacks, rollbacks)
        self.assertIs(manager._read_conns[key], fresh_reader)
        self.assertEqual(manager._write_conns, {})
        self.assertNotIn(key, manager._writer_read_paths)
        manager.close()
        self.assertEqual(self.connect.counts.active_connections, 0)

    def test_maintenance_is_only_blocked_by_leases_on_the_same_database(self):
        manager = MdbConnectionManager()
        quiet_key = os.path.normcase(os.path.abspath("quiet.mdb"))
        with manager.connection("busy.mdb") as busy:
            with manager.maintenance("quiet.mdb"):
                self.assertEqual(manager._maintenance_paths, {quiet_key})
                busy.cursor().execute("SELECT")
                with manager.connection("busy.mdb") as nested:
                    self.assertIs(nested._conn, busy._conn)
            # The same database is refused whatever the spelling of its path.
            with self.assertRaisesRegex(RuntimeError, "active operations"):
                with manager.maintenance(os.path.abspath("BUSY.MDB")):
                    self.fail("maintenance granted under a lease on that database")
            self.assertFalse(busy._conn.closed)
        self.assertEqual(manager._maintenance_paths, set())
        manager.close()
        self.assertEqual(self.connect.counts.active_connections, 0)

    def test_the_database_lock_is_reentrant_for_nested_use_on_one_thread(self):
        manager = MdbConnectionManager()
        outcome = []

        def nested_use() -> None:
            with manager.connection("reentrant.mdb") as outer:
                with manager.connection("reentrant.mdb") as inner:
                    outcome.append(inner._conn is outer._conn)
                manager.use_committed_writer_for_reads("reentrant.mdb")
                manager.close_database("reentrant.mdb")
            outcome.append("done")

        # A watchdog thread: a non-reentrant lock would hang, not fail.
        worker = threading.Thread(target=nested_use, daemon=True)
        worker.start()
        worker.join(timeout=10.0)
        self.assertFalse(worker.is_alive(), "nested use of one database deadlocked")
        self.assertEqual(outcome, [True, "done"])
        self.assertEqual(manager._active_leases, {})
        manager.close()
        self.assertEqual(self.connect.counts.active_connections, 0)

    def test_nested_error_on_a_handle_replaced_in_the_pool_flags_nothing(self):
        # The nested failure site must check that the pool still holds THIS
        # handle, not merely that the key is occupied: a replacement pooled
        # while the lease was open must stay open and unflagged.
        manager = MdbConnectionManager()
        with manager.connection("nested-replaced.mdb") as outer:
            condemned = outer._conn
            with self.assertRaisesRegex(pyodbc.OperationalError, "communication"):
                with manager.connection("nested-replaced.mdb"):
                    manager.close_database("nested-replaced.mdb")
                    self.assertTrue(condemned.closed)
                    with manager.connection("nested-replaced.mdb") as third:
                        replacement = third._conn
                    self.assertIsNot(replacement, condemned)
                    raise pyodbc.OperationalError("08S01", "communication link failed")
            self.assertNotIn(id(condemned), manager._unhealthy_connection_ids)
            self.assertNotIn(id(condemned), manager._deferred_eviction_ids)
        self.assertFalse(replacement.closed)
        manager.close()
        self.assertEqual(manager._unhealthy_connection_ids, set())
        self.assertEqual(manager._deferred_eviction_ids, set())
        self.assertEqual(self.connect.counts.active_connections, 0)

    def test_overlapping_maintenance_keeps_each_database_guarded_until_its_own_end(
        self,
    ):
        manager = MdbConnectionManager()
        first_key = os.path.normcase(os.path.abspath("first.mdb"))
        with manager.maintenance("first.mdb"):
            with manager.maintenance("second.mdb"):
                self.assertEqual(len(manager._maintenance_paths), 2)
            # Ending the second maintenance releases only the second database.
            self.assertEqual(manager._maintenance_paths, {first_key})
            with self.assertRaisesRegex(RuntimeError, "maintenance"):
                with manager.connection("first.mdb"):
                    self.fail("lease granted during maintenance of that database")
        self.assertEqual(manager._maintenance_paths, set())
        with manager.connection("first.mdb"):
            pass
        manager.close()
        self.assertEqual(self.connect.counts.active_connections, 0)

    def test_a_non_driver_failure_in_the_health_probe_propagates_and_flags_nothing(
        self,
    ):
        # Only driver errors mean the handle is dead; a bug elsewhere must not
        # be mistaken for that and silently replace a healthy cached handle.
        manager = MdbConnectionManager()
        key = os.path.normcase(os.path.abspath("probe-bug.mdb"))
        with manager.connection("probe-bug.mdb"):
            pass
        cached = manager._read_conns[key]
        with patch.object(cached, "cursor", side_effect=RuntimeError("probe bug")):
            with self.assertRaisesRegex(RuntimeError, "probe bug"):
                with manager.connection("probe-bug.mdb"):
                    self.fail("lease granted although the probe raised")
        self.assertIs(manager._read_conns[key], cached)
        self.assertFalse(cached.closed)
        self.assertEqual(manager._unhealthy_connection_ids, set())
        self.assertEqual(manager._active_leases, {})
        manager.close()
        self.assertEqual(self.connect.counts.active_connections, 0)
