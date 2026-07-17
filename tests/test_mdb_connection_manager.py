import threading
import unittest
from unittest.mock import patch
import pyodbc
from ost_visualizer.infrastructure.mdb.connection_manager import (
    MdbConnectionManager,
)
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from ost_visualizer.infrastructure.persistence.repositories.file_project_repository import (
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
        self.commits = 0
        self.rollbacks = 0
        self.connections = []


class _FakeCursor:
    def __init__(self, counts: _LifecycleCounts) -> None:
        self._counts = counts
        self._closed = False
        counts.cursors_created += 1
        counts.active_cursors += 1

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        # pyodbc cursor context managers commit or roll back; they do not close.
        pass

    def execute(self, sql: str):
        if sql == "RAISE_QUERY_ERROR":
            raise pyodbc.OperationalError("query failed")
        return self

    def fetchall(self):
        return [("row",)]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._counts.cursors_closed += 1
        self._counts.active_cursors -= 1


class _FakeConnection:
    def __init__(
        self,
        counts: _LifecycleCounts,
        connection_string: str,
        autocommit: bool,
    ) -> None:
        self.counts = counts
        self.connection_string = connection_string
        self.autocommit = autocommit
        self.closed = False
        self.owner_thread_id = threading.get_ident()
        counts.connections_opened += 1
        counts.active_connections += 1
        counts.connections.append(self)

    def cursor(self):
        if self.closed:
            raise pyodbc.OperationalError("connection is closed")
        return _FakeCursor(self.counts)

    def commit(self) -> None:
        self.counts.commits += 1

    def rollback(self) -> None:
        self.counts.rollbacks += 1

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.counts.connections_closed += 1
        self.counts.active_connections -= 1

    def getinfo(self, _info_type):
        return self.connection_string


class _FakeConnect:
    def __init__(self) -> None:
        self.counts = _LifecycleCounts()
        self.max_opens = None

    def __call__(self, connection_string: str, *, autocommit: bool):
        if (
            self.max_opens is not None
            and self.counts.connections_opened >= self.max_opens
        ):
            raise pyodbc.OperationalError("Too many client tasks")
        return _FakeConnection(self.counts, connection_string, autocommit)


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

    def test_failed_write_rolls_back_and_releases_cursor_and_connection(self):
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        with self.assertRaisesRegex(pyodbc.OperationalError, "query failed"):
            with writer._connection("write-error.mdb") as connection:
                connection.cursor().execute("RAISE_QUERY_ERROR")
        self.assertEqual(self.connect.counts.commits, 0)
        self.assertEqual(self.connect.counts.rollbacks, 1)
        self.assert_all_resources_released()

    def test_query_exception_closes_cursor_and_invalidates_connection(self):
        manager = MdbConnectionManager()
        with self.assertRaisesRegex(pyodbc.OperationalError, "query failed"):
            with manager.connection("query-error.mdb") as connection:
                connection.cursor().execute("RAISE_QUERY_ERROR")
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

    def test_refresh_closes_only_requested_cached_read_connection(self):
        manager = MdbConnectionManager()
        with manager.connection("old.mdb"):
            pass
        with manager.connection("new.mdb"):
            pass
        manager.close_read("old.mdb")
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

    def test_post_write_refreshes_reuse_committed_write_connection(self):
        self.connect.max_opens = 32
        manager = MdbConnectionManager()
        writer = MdbWriter(conn_manager=manager)
        parser = MdbFileParser(parser=_MaterializingRawBidReader(conn_manager=manager))
        with manager.connection("refresh.mdb"):
            pass
        for _index in range(500):
            with writer._connection("refresh.mdb"):
                pass
            manager.close_read("refresh.mdb")
            raw_data = parser.get_raw_bid_data("refresh.mdb", "bid-1")
            self.assertEqual(raw_data.bid_row["UID"], "bid-1")
        self.assertEqual(self.connect.counts.connections_opened, 2)
        self.assertEqual(self.connect.counts.active_connections, 1)
        self.assertEqual(len(manager._read_conns), 0)
        self.assertEqual(len(manager._write_conns), 1)
        self.assertEqual(self.connect.counts.rollbacks, 500)
        manager.close()
        self.assert_all_resources_released()

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
