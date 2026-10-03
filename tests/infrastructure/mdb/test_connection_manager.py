import os
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
        self.assertFalse(second_entered.wait(timeout=0.05))
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
        with self.assertRaises(pyodbc.Error):
            with manager.maintenance(path):
                self.fail("failed close permitted maintenance")
        self.assertIs(manager._read_conns[path], conn)
        self.assertFalse(manager._maintenance_paths)


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
        self.assertFalse(second_entered.wait(timeout=0.1))
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
                with self.assertRaisesRegex(
                    TypeError, "does not accept cursor options"
                ):
                    strict.cursor(*args, **kwargs)
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
