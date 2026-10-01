import sqlite3
import unittest
from ost_visualizer.infrastructure.database.bid_owned_identity import (
    DuplicateBidOwnedUidError,
    IncoherentBidOwnedScopeError,
    MalformedBidOwnedUidError,
    MissingBidOwnedUidError,
    require_single_bid_scope_for_uids,
)
from tests.helpers.mdb.operations import (
    _ParameterLimitedSqliteCursorWrapper,
    _SqliteCursorWrapper,
)


def _scope_database(bids, pages):
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE Bids (UID INTEGER)")
    connection.executemany("INSERT INTO Bids VALUES (?)", ((uid,) for uid in bids))
    connection.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
    connection.executemany("INSERT INTO BidPages VALUES (?, ?)", pages)
    return connection


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
                # Every target UID is queried exactly once in bounded chunks,
                # followed by the single owner lookup.
                full_chunks, remainder = divmod(row_count, 50)
                expected_counts = [50] * full_chunks
                if remainder:
                    expected_counts.append(remainder)
                self.assertEqual(cursor.parameter_counts, expected_counts + [1])

    def test_scope_preflight_rejects_targets_from_different_bids(self):
        connection = _scope_database((1, 2), ((10, 1), (11, 2)))
        with self.assertRaises(IncoherentBidOwnedScopeError):
            require_single_bid_scope_for_uids(
                _SqliteCursorWrapper(connection), "BidPages", (10, 11)
            )
        self.assertEqual(
            require_single_bid_scope_for_uids(
                _SqliteCursorWrapper(connection), "BidPages", (11,)
            ),
            2,
        )

    def test_scope_preflight_rejects_unowned_targets(self):
        connection = _scope_database((1,), ((10, 1), (11, None)))
        with self.assertRaises(IncoherentBidOwnedScopeError):
            require_single_bid_scope_for_uids(
                _SqliteCursorWrapper(connection), "BidPages", (10, 11)
            )

    def test_scope_preflight_requires_existing_targets_and_owner(self):
        connection = _scope_database((1,), ((10, 1), (12, 5)))
        with self.assertRaisesRegex(MissingBidOwnedUidError, "no row for UID 99"):
            require_single_bid_scope_for_uids(
                _SqliteCursorWrapper(connection), "BidPages", (10, 99)
            )
        with self.assertRaisesRegex(MissingBidOwnedUidError, "at least one"):
            require_single_bid_scope_for_uids(
                _SqliteCursorWrapper(connection), "BidPages", ()
            )
        with self.assertRaisesRegex(MissingBidOwnedUidError, "Bids has no row"):
            require_single_bid_scope_for_uids(
                _SqliteCursorWrapper(connection), "BidPages", (12,)
            )

    def test_scope_preflight_rejects_malformed_and_duplicate_authoritative_uids(self):
        connection = _scope_database((1,), ((10, 1), (10, 1)))
        for malformed in (0, -3, "x", None, "1.5"):
            with self.subTest(malformed=malformed):
                with self.assertRaises(MalformedBidOwnedUidError):
                    require_single_bid_scope_for_uids(
                        _SqliteCursorWrapper(connection), "BidPages", (malformed,)
                    )
        with self.assertRaises(DuplicateBidOwnedUidError):
            require_single_bid_scope_for_uids(
                _SqliteCursorWrapper(connection), "BidPages", (10,)
            )

    def test_scope_preflight_ignores_repeated_requested_uids(self):
        connection = _scope_database((1,), ((10, 1),))
        cursor = _ParameterLimitedSqliteCursorWrapper(connection, 255)
        self.assertEqual(
            require_single_bid_scope_for_uids(cursor, "BidPages", (10, "10", 10)), 1
        )
        self.assertEqual(cursor.parameter_counts, [1, 1])
