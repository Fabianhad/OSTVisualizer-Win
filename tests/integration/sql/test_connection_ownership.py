import os
import unittest

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
        cursor.close()
        lease.close()
        self.assertEqual(raw_connection.raw_cursor.close_count, 1)
        self.assertEqual(raw_connection.close_count, 1)
