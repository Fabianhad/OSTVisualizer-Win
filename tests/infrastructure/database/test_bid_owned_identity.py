import sqlite3
import time
import unittest
from ost_visualizer.application.dtos.collaboration_dtos import PlanTakeoffOwnership
from ost_visualizer.infrastructure.database.bid_owned_identity import (
    CyclicBidOwnedReferenceError,
    DanglingBidOwnedReferenceError,
    DuplicateBidOwnedUidError,
    IncoherentBidOwnedScopeError,
    MalformedBidOwnedUidError,
    MissingBidOwnedUidError,
    require_acyclic_bid_owned_parent_graph,
    require_existing_bid_owned_references,
    require_existing_bid_scoped_uid_match,
    require_existing_bid_scoped_uid_matches,
    require_existing_unique_bid_owned_uid_matches,
    require_plan_takeoff_ownership,
    require_single_bid_scope_for_uids,
    require_takeoff_parent_pages,
    require_unique_bid_owned_uid_matches,
    require_valid_unique_bid_owned_uids,
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


class _ColumnSchema:
    def __init__(self, columns):
        self._columns = columns

    def column_exists(self, table, column):
        return (table, column) in self._columns


class BidOwnedIdentityContractTests(unittest.TestCase):
    """Second pass: direct contracts of the shared (Access and SQL) preflights.
    The sqlite connection stands in for Access (``?`` parameters, ``[ ]``
    identifiers); the parameter-limited cursor counts every UID parameter so the
    bounded-set rule is checked on the statements themselves.
    """

    def test_authoritative_uids_are_positive_ascii_decimals_and_unique(self):
        require_valid_unique_bid_owned_uids([1, "2", "30"], "BidPages")
        for malformed, rendered in (
            (0, "0"),
            ("0", "0"),
            (-1, "-1"),
            ("1.5", "1.5"),
            (None, "<missing>"),
            ("", "<missing>"),
            ("x", "x"),
            (" 1", " 1"),
            ("٣", "٣"),
            (True, "True"),
        ):
            with self.subTest(malformed=malformed):
                with self.assertRaisesRegex(
                    MalformedBidOwnedUidError,
                    f"BidPages contains malformed UID {rendered}; "
                    "authoritative bid-owned UIDs must be positive integers",
                ):
                    require_valid_unique_bid_owned_uids([1, malformed], "BidPages")
        for duplicated in ([7, "7"], ["007", 7], [7, 8, "7"]):
            with self.subTest(duplicated=duplicated):
                with self.assertRaisesRegex(
                    DuplicateBidOwnedUidError, "BidPages contains duplicate UID 7;"
                ):
                    require_valid_unique_bid_owned_uids(duplicated, "BidPages")

    def test_unique_matches_return_only_stored_uids_in_bounded_queries(self):
        connection = _scope_database((1,), ((10, 1), (11, 1), (11, 1), (12, 1)))
        cursor = _ParameterLimitedSqliteCursorWrapper(connection, 255)
        self.assertEqual(
            require_unique_bid_owned_uid_matches(cursor, "BidPages", (10, "10", 99)),
            {10},
        )
        self.assertEqual(cursor.parameter_counts, [2])
        self.assertEqual(
            require_unique_bid_owned_uid_matches(cursor, "BidPages", ()), set()
        )
        self.assertEqual(cursor.parameter_counts, [2])
        with self.assertRaises(DuplicateBidOwnedUidError):
            require_unique_bid_owned_uid_matches(cursor, "BidPages", (11,))
        with self.assertRaises(MalformedBidOwnedUidError):
            require_unique_bid_owned_uid_matches(cursor, "BidPages", (12, 0))
        # A malformed UID is rejected before any statement is sent.
        self.assertEqual(cursor.parameter_counts, [2, 1])

    def test_existing_matches_report_the_lowest_missing_uid(self):
        connection = _scope_database((1, 2), ((10, 1),))
        cursor = _SqliteCursorWrapper(connection)
        self.assertIsNone(
            require_existing_unique_bid_owned_uid_matches(cursor, "BidPages", ("10",))
        )
        self.assertIsNone(
            require_existing_unique_bid_owned_uid_matches(cursor, "Bids", (1, 2))
        )
        with self.assertRaisesRegex(
            MissingBidOwnedUidError,
            r"BidPages has no row for UID 12; "
            r"the requested authoritative owner does not exist\.",
        ):
            require_existing_unique_bid_owned_uid_matches(
                cursor, "BidPages", (30, 12, 10)
            )
        with self.assertRaisesRegex(
            MissingBidOwnedUidError, "Bids has no row for UID 3"
        ):
            require_existing_unique_bid_owned_uid_matches(cursor, "Bids", (1, 3))

    def test_bid_scoped_matches_require_every_target_to_belong_to_the_bid(self):
        connection = _scope_database((1, 2), ((10, 1), (11, 2), (12, None), (13, 1)))
        cursor = _SqliteCursorWrapper(connection)
        self.assertIsNone(
            require_existing_bid_scoped_uid_matches(cursor, "BidPages", (10, "13"), "1")
        )
        self.assertIsNone(
            require_existing_bid_scoped_uid_match(cursor, "BidPages", 11, 2)
        )
        with self.assertRaisesRegex(
            MissingBidOwnedUidError,
            r"BidPages\.UID=11 does not belong to Bids\.UID=1\.",
        ):
            require_existing_bid_scoped_uid_matches(cursor, "BidPages", (10, 11), 1)
        # The first offender in request order is named, and an unowned row is
        # not in any bid's scope.
        with self.assertRaisesRegex(
            MissingBidOwnedUidError, r"BidPages\.UID=12 does not belong"
        ):
            require_existing_bid_scoped_uid_matches(cursor, "BidPages", (12, 11), 1)
        with self.assertRaisesRegex(
            MissingBidOwnedUidError, "BidPages has no row for UID 99"
        ):
            require_existing_bid_scoped_uid_matches(cursor, "BidPages", (10, 99), 1)
        with self.assertRaises(MalformedBidOwnedUidError):
            require_existing_bid_scoped_uid_matches(cursor, "BidPages", (10, 0), 1)

    def test_bid_scoped_matches_require_the_owning_bid_row_to_exist(self):
        connection = _scope_database((), ((10, 5),))
        with self.assertRaisesRegex(
            MissingBidOwnedUidError, "Bids has no row for UID 5"
        ):
            require_existing_bid_scoped_uid_matches(
                _SqliteCursorWrapper(connection), "BidPages", (10,), 5
            )
        duplicated = _scope_database((1,), ((10, 1), (10, 1)))
        with self.assertRaises(DuplicateBidOwnedUidError):
            require_existing_bid_scoped_uid_matches(
                _SqliteCursorWrapper(duplicated), "BidPages", (10,), 1
            )

    def test_bid_scoped_matches_stay_bounded_and_skip_empty_requests(self):
        connection = _scope_database((1,), ((uid, 1) for uid in range(1, 121)))
        cursor = _ParameterLimitedSqliteCursorWrapper(connection, 255)
        require_existing_bid_scoped_uid_matches(
            cursor, "BidPages", list(range(1, 121)) + [5, "5"], 1
        )
        # 120 distinct targets in sets of at most 50, then the single owner row.
        self.assertEqual(cursor.parameter_counts, [50, 50, 20, 1])
        empty_cursor = _ParameterLimitedSqliteCursorWrapper(
            _scope_database((), ()), 255
        )
        self.assertIsNone(
            require_existing_bid_scoped_uid_matches(empty_cursor, "BidPages", (), 5)
        )
        self.assertEqual(empty_cursor.parameter_counts, [])

    def test_single_bid_scope_names_the_missing_uid_and_requires_the_bid_row(self):
        connection = _scope_database((1,), ((10, 1), (11, 1)))
        cursor = _ParameterLimitedSqliteCursorWrapper(connection, 255)
        self.assertEqual(
            require_single_bid_scope_for_uids(cursor, "BidPages", (11, 10)), 1
        )
        with self.assertRaisesRegex(
            MissingBidOwnedUidError,
            r"BidPages has no row for UID 77; "
            r"the requested authoritative owner does not exist\.",
        ):
            require_single_bid_scope_for_uids(cursor, "BidPages", (99, 77, 10))
        with self.assertRaisesRegex(
            IncoherentBidOwnedScopeError,
            "BidPages mutation targets do not belong to one authoritative Bid",
        ):
            require_single_bid_scope_for_uids(
                _SqliteCursorWrapper(_scope_database((1, 2), ((10, 1), (11, 2)))),
                "BidPages",
                (10, 11),
            )

    def test_takeoff_parents_must_be_on_the_same_page_as_the_takeoff(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE BidTakeoffs (UID INTEGER, BidPageUID INTEGER)")
        connection.executemany(
            "INSERT INTO BidTakeoffs VALUES (?, ?)", ((1, 100), (2, 100), (3, 200))
        )
        cursor = _ParameterLimitedSqliteCursorWrapper(connection, 255)
        self.assertIsNone(
            require_takeoff_parent_pages(cursor, [(1, 100), ("2", "100"), (1, 100)])
        )
        # Each distinct parent is fetched once.
        self.assertEqual(cursor.parameter_counts, [2])
        for pairs in ([(3, 100)], [(1, 200)], [(9, 100)], [(1, 100), (3, 100)]):
            with self.subTest(pairs=pairs):
                with self.assertRaisesRegex(
                    IncoherentBidOwnedScopeError,
                    "A Takeoff and its parent must belong to the same Page.",
                ):
                    require_takeoff_parent_pages(cursor, pairs)

    def test_plan_ownership_snapshot_must_still_match_the_stored_takeoffs(self):
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidPageUID INTEGER, "
            "BidConditionUID INTEGER, BidAreaUID INTEGER, ParentUID INTEGER)"
        )
        connection.executemany(
            "INSERT INTO BidTakeoffs VALUES (?, ?, ?, ?, ?)",
            ((1, 10, 20, 30, None), (2, 10, 20, None, 1)),
        )
        cursor = _ParameterLimitedSqliteCursorWrapper(connection, 255)
        full = _ColumnSchema(
            {("BidTakeoffs", "BidAreaUID"), ("BidTakeoffs", "ParentUID")}
        )
        snapshot = (
            PlanTakeoffOwnership("1", "10", "20", "30", "0"),
            PlanTakeoffOwnership("2", "10", "20", "0", "1"),
        )
        self.assertIsNone(
            require_plan_takeoff_ownership(cursor, full, (1, 2), snapshot)
        )
        self.assertEqual(cursor.parameter_counts, [2])
        # No snapshot, no preflight query.
        self.assertIsNone(require_plan_takeoff_ownership(cursor, full, (1, 2), ()))
        self.assertEqual(cursor.parameter_counts, [2])
        stale = (
            PlanTakeoffOwnership("1", "10", "20", "30", "0"),
            PlanTakeoffOwnership("2", "11", "20", "0", "1"),
        )
        for changed in (
            stale,
            (
                PlanTakeoffOwnership("1", "10", "21", "30", "0"),
                snapshot[1],
            ),
            (
                PlanTakeoffOwnership("1", "10", "20", "31", "0"),
                snapshot[1],
            ),
            (
                snapshot[0],
                PlanTakeoffOwnership("2", "10", "20", "0", "0"),
            ),
        ):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(
                    MissingBidOwnedUidError,
                    "takeoff ownership changed before the Plan mutation started",
                ):
                    require_plan_takeoff_ownership(cursor, full, (1, 2), changed)
        with self.assertRaisesRegex(
            MissingBidOwnedUidError, "ownership changed before the Plan mutation"
        ):
            require_plan_takeoff_ownership(
                cursor,
                full,
                (1, 2, 3),
                snapshot + (PlanTakeoffOwnership("3", "10", "20", "0", "0"),),
            )

    def test_plan_ownership_snapshot_must_cover_each_target_exactly_once(self):
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidPageUID INTEGER, "
            "BidConditionUID INTEGER)"
        )
        connection.execute("INSERT INTO BidTakeoffs VALUES (1, 10, 20)")
        cursor = _ParameterLimitedSqliteCursorWrapper(connection, 255)
        legacy = _ColumnSchema(set())
        entry = PlanTakeoffOwnership("1", "10", "20", "0", "0")
        # Missing optional columns read as 0, matching a snapshot of 0.
        self.assertIsNone(
            require_plan_takeoff_ownership(cursor, legacy, (1,), (entry,))
        )
        for targets, snapshot in (
            ((1, 2), (entry,)),
            ((1,), (entry, PlanTakeoffOwnership("2", "10", "20", "0", "0"))),
            ((1,), (entry, entry)),
        ):
            with self.subTest(targets=targets, snapshot=len(snapshot)):
                with self.assertRaisesRegex(
                    ValueError, "must cover every validation target exactly once"
                ):
                    require_plan_takeoff_ownership(cursor, legacy, targets, snapshot)
        self.assertEqual(cursor.parameter_counts, [1])

    def test_references_must_point_at_an_existing_parent_in_canonical_form(self):
        require_existing_bid_owned_references(
            [(3, 5), ("4", "007"), (5, 7)],
            [5, "7"],
            child_table="BidTakeoffs",
            child_column="ParentUID",
            parent_table="BidTakeoffs",
        )
        with self.assertRaisesRegex(
            DanglingBidOwnedReferenceError,
            r"BidTakeoffs\.UID=3 references missing BidTakeoffs\.UID=9 "
            r"through ParentUID\.",
        ):
            require_existing_bid_owned_references(
                [(2, 5), ("003", "9")],
                [5, 7],
                child_table="BidTakeoffs",
                child_column="ParentUID",
                parent_table="BidTakeoffs",
            )

    def test_parent_graphs_accept_forests_and_ignore_root_markers(self):
        require_acyclic_bid_owned_parent_graph({}, "BidConditionFolders")
        require_acyclic_bid_owned_parent_graph(
            {1: None, 2: 1, 3: 2, 4: "0", 5: 0, 6: "", 7: 1, "8": "7"},
            "BidConditionFolders",
        )
        # Two chains converging on one parent are not a cycle.
        require_acyclic_bid_owned_parent_graph({1: 3, 2: 3, 3: 4}, "BidPageFolders")

    def test_parent_graph_cycles_are_reported_by_their_lowest_numeric_member(self):
        cases = (
            ({1: 1}, "1"),
            ({1: 2, 2: 1}, "1"),
            ({10: 9, 9: 10}, "9"),
            # The unrelated entry leading into the cycle is not a member.
            ({1: 2, 2: 3, 3: 2}, "2"),
            ({1: 2, 2: 3, 3: 4, 4: 3}, "3"),
            # A cycle found after an acyclic chain was fully explored.
            ({1: 2, 2: 0, 5: 6, 6: 5}, "5"),
            ({"a": "b", "b": "a"}, "a"),
            ({"a": "b", "b": "a", "10": "9", "9": "10"}, "9"),
        )
        for parents, expected in cases:
            with self.subTest(parents=parents):
                with self.assertRaisesRegex(
                    CyclicBidOwnedReferenceError,
                    rf"^BidConditionFolders\.UID={expected} participates in a "
                    r"ParentUID cycle\.$",
                ):
                    require_acyclic_bid_owned_parent_graph(
                        parents, "BidConditionFolders"
                    )
        with self.assertRaisesRegex(
            CyclicBidOwnedReferenceError, r"BidPageFolders\.UID=2 .* ParentFolderUID "
        ):
            require_acyclic_bid_owned_parent_graph(
                {2: 3, 3: 2}, "BidPageFolders", parent_column="ParentFolderUID"
            )

    def test_plan_ownership_snapshot_rejects_duplicate_physical_takeoff_rows(self):
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidPageUID INTEGER, "
            "BidConditionUID INTEGER, BidAreaUID INTEGER, ParentUID INTEGER)"
        )
        # Two physical rows for UID 1 with identical ownership collapse into
        # one expected tuple, so only the row count can expose the duplicate.
        connection.executemany(
            "INSERT INTO BidTakeoffs VALUES (?, ?, ?, ?, ?)",
            ((1, 10, 20, 30, None), (1, 10, 20, 30, None)),
        )
        schema = _ColumnSchema(
            {("BidTakeoffs", "BidAreaUID"), ("BidTakeoffs", "ParentUID")}
        )
        with self.assertRaisesRegex(
            MissingBidOwnedUidError, "ownership changed before the Plan mutation"
        ):
            require_plan_takeoff_ownership(
                _SqliteCursorWrapper(connection),
                schema,
                (1,),
                (PlanTakeoffOwnership("1", "10", "20", "30", "0"),),
            )

    def test_single_bid_scoped_match_rejects_a_target_outside_the_bid(self):
        connection = _scope_database((1, 2), ((10, 1), (11, 2)))
        cursor = _SqliteCursorWrapper(connection)
        with self.assertRaisesRegex(
            MissingBidOwnedUidError,
            r"BidPages\.UID=11 does not belong to Bids\.UID=1\.",
        ):
            require_existing_bid_scoped_uid_match(cursor, "BidPages", 11, 1)
        with self.assertRaisesRegex(
            MissingBidOwnedUidError, "BidPages has no row for UID 12"
        ):
            require_existing_bid_scoped_uid_match(cursor, "BidPages", 12, 1)

    def test_parent_graph_walk_is_linear_for_long_acyclic_chains(self):
        # Every start would walk the whole chain again without the explored
        # set (quadratic): 8000 nodes is ~32M steps unguarded and ~8k guarded.
        chain = {uid: uid - 1 for uid in range(1, 8001)}
        started = time.perf_counter()
        require_acyclic_bid_owned_parent_graph(chain, "BidConditionFolders")
        self.assertLess(time.perf_counter() - started, 1.5)
        chain[1] = 8000
        with self.assertRaisesRegex(CyclicBidOwnedReferenceError, r"UID=1 "):
            require_acyclic_bid_owned_parent_graph(chain, "BidConditionFolders")

    def test_parent_graph_cycle_ordering_treats_only_ascii_digits_as_numbers(self):
        for parents, expected in (
            ({"\u0663": "a", "a": "\u0663"}, "a"),
            ({"\u0663": "\u0664", "\u0664": "\u0663", "9": "10", "10": "9"}, "9"),
        ):
            with self.subTest(parents=parents):
                with self.assertRaisesRegex(
                    CyclicBidOwnedReferenceError, rf"^T\.UID={expected} participates"
                ):
                    require_acyclic_bid_owned_parent_graph(parents, "T")
