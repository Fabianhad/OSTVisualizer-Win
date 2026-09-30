import sqlite3
import unittest
from ost_visualizer.infrastructure.database.bid_owned_identity import (
    require_single_bid_scope_for_uids,
)
from tests.helpers.mdb.operations import (
    _ParameterLimitedSqliteCursorWrapper,
    _SqliteCursorWrapper,
    _SqliteRow,
)


class BidOwnedIdentityPersistenceTests(unittest.TestCase):
    def test_bid_owned_preflight_chunks_around_access_parameter_limit(self):
        for row_count in (50, 51, 254, 255, 256):
            with self.subTest(row_count=row_count):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE Bids (UID INTEGER)")
                conn.execute("INSERT INTO Bids VALUES (1)")
                conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
                conn.executemany(
                    "INSERT INTO BidPages VALUES (?, 1)",
                    ((uid,) for uid in range(1, row_count + 1)),
                )
                cursor = _ParameterLimitedSqliteCursorWrapper(conn, 255)
                self.assertEqual(
                    require_single_bid_scope_for_uids(
                        cursor, "BidPages", range(1, row_count + 1)
                    ),
                    1,
                )
                self.assertLessEqual(max(cursor.parameter_counts), 50)
