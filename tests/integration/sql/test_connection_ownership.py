import os
import unittest
import pyodbc

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.infrastructure.database.connection_wrapper import ConnectionWrapper
from ost_visualizer.infrastructure.sql.connection_manager import (
    SqlConnectionLease,
    SqlConnectionManager,
    SqlConnectionRequest,
)
from tests.helpers.sql.cleanup_support import (
    _RawConnection as _cleanup_support__RawConnection,
    _RawCursor as _cleanup_support__RawCursor,
)


class ConnectionOwnershipSqlCleanupTests(unittest.TestCase):
    def test_sql_cursor_has_one_owner_and_is_closed_once(self):
        raw_connection = _cleanup_support__RawConnection()
        lease = SqlConnectionLease(raw_connection, 30)
        wrapper = ConnectionWrapper(lease, accepts_cursor_options=False)
        cursor = wrapper.cursor()
        # The lease applies the command timeout to the single raw cursor it owns.
        self.assertEqual(raw_connection.raw_cursor.timeout, 30)
        cursor.close()
        self.assertEqual(raw_connection.raw_cursor.close_count, 1)
        self.assertEqual(raw_connection.close_count, 0)
        lease.close()
        self.assertEqual(raw_connection.raw_cursor.close_count, 1)
        self.assertEqual(raw_connection.close_count, 1)
        # Every owner is idempotent: repeated closes never reach the driver again.
        cursor.close()
        lease.close()
        self.assertEqual(raw_connection.raw_cursor.close_count, 1)
        self.assertEqual(raw_connection.close_count, 1)

    def test_lease_closes_a_cursor_left_open_exactly_once(self):
        raw_connection = _cleanup_support__RawConnection()
        lease = SqlConnectionLease(raw_connection, 30)
        wrapper = ConnectionWrapper(lease, accepts_cursor_options=False)
        cursor = wrapper.cursor()
        lease.close()
        self.assertEqual(raw_connection.raw_cursor.close_count, 1)
        self.assertEqual(raw_connection.close_count, 1)
        cursor.close()
        self.assertEqual(raw_connection.raw_cursor.close_count, 1)
        with self.assertRaises(RuntimeError):
            lease.cursor()

    def test_a_cursor_that_fails_to_close_never_keeps_the_connection_open(self):
        for error, propagates in (
            (pyodbc.Error("cursor close failed"), False),
            (RuntimeError("unexpected"), True),
        ):
            with self.subTest(error=type(error).__name__):
                raw_connection = _cleanup_support__RawConnection()
                raw_connection.raw_cursor.close = _raise(error)
                lease = SqlConnectionLease(raw_connection, 30)
                lease.cursor()
                if propagates:
                    with self.assertRaises(type(error)) as raised:
                        lease.close()
                    self.assertIs(raised.exception, error)
                else:
                    lease.close()
                self.assertEqual(raw_connection.close_count, 1)
                lease.close()
                self.assertEqual(raw_connection.close_count, 1)
                with self.assertRaises(RuntimeError):
                    lease.cursor()

    def test_a_connection_that_fails_to_close_is_not_closed_again(self):
        raw_connection = _cleanup_support__RawConnection()
        calls = []

        def failing_close():
            calls.append("close")
            raise pyodbc.Error("connection close failed")

        raw_connection.close = failing_close
        lease = SqlConnectionLease(raw_connection, 30)
        lease.close()
        lease.close()
        self.assertEqual(calls, ["close"])

    def test_a_cursor_closed_with_an_error_is_forgotten_by_its_lease(self):
        raw_connection = _cleanup_support__RawConnection()
        calls = []

        def failing_close():
            calls.append("close")
            raise RuntimeError("cursor close failed")

        raw_connection.raw_cursor.close = failing_close
        lease = SqlConnectionLease(raw_connection, 30)
        cursor = lease.cursor()
        with self.assertRaisesRegex(RuntimeError, "cursor close failed"):
            cursor.close()
        # The lease's ownership list (white-box): a cursor whose close raised has
        # still left it, so a long-lived lease does not accumulate dead cursors.
        self.assertEqual(lease._cursors, [])
        lease.close()
        cursor.close()
        self.assertEqual(calls, ["close"])
        self.assertEqual(raw_connection.close_count, 1)

    def test_cursors_are_closed_newest_first_before_the_connection(self):
        events = []
        raw_connection = _cleanup_support__RawConnection()
        cursors = []

        def next_cursor():
            raw = _cleanup_support__RawCursor()
            number = len(cursors)
            raw.close = lambda number=number: events.append(f"cursor {number}")
            cursors.append(raw)
            return raw

        raw_connection.cursor = next_cursor
        raw_connection.close = lambda: events.append("connection")
        lease = SqlConnectionLease(raw_connection, 30)
        for _ in range(3):
            lease.cursor()
        lease.close()
        self.assertEqual(events, ["cursor 2", "cursor 1", "cursor 0", "connection"])


def _raise(error):
    def raiser():
        raise error

    return raiser
