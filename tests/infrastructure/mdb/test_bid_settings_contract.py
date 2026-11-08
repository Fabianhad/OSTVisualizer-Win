import unittest
from ost_visualizer.infrastructure.mdb.bid_settings_contract import (
    BidSettingsCardinalityError,
    fetch_optional_bid_settings_row,
)


class _ScriptedCursor:
    """Cursor stand-in that serves a scripted fetchone() sequence."""

    def __init__(self, rows, execute_error=None):
        self._rows = list(rows)
        self._execute_error = execute_error
        self.executed = []
        self.fetch_count = 0

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        if self._execute_error is not None:
            raise self._execute_error
        return self

    def fetchone(self):
        self.fetch_count += 1
        return self._rows.pop(0) if self._rows else None


class FetchOptionalBidSettingsRowTests(unittest.TestCase):
    def test_no_row_returns_none_after_a_single_fetch(self):
        cursor = _ScriptedCursor([])
        self.assertIsNone(fetch_optional_bid_settings_row(cursor, 5, ("A",)))
        self.assertEqual(cursor.fetch_count, 1)

    def test_single_row_is_returned_unchanged_after_checking_for_a_second(self):
        row = (11, "x")
        cursor = _ScriptedCursor([row])
        self.assertIs(fetch_optional_bid_settings_row(cursor, 5, ("A", "B")), row)
        self.assertEqual(cursor.fetch_count, 2)

    def test_query_selects_bracketed_columns_in_order_for_the_bid(self):
        cursor = _ScriptedCursor([])
        fetch_optional_bid_settings_row(cursor, 42, ("BidUID", "Name", "Zoom"))
        self.assertEqual(
            cursor.executed,
            [
                (
                    "SELECT [BidUID], [Name], [Zoom] FROM [BidSettings] "
                    "WHERE [BidUID]=?",
                    (42,),
                )
            ],
        )

    def test_bid_uid_is_bound_as_a_parameter_not_interpolated(self):
        cursor = _ScriptedCursor([])
        hostile = "1; DROP TABLE [BidSettings]"
        fetch_optional_bid_settings_row(cursor, hostile, ("A",))
        self.assertEqual(
            cursor.executed,
            [("SELECT [A] FROM [BidSettings] WHERE [BidUID]=?", (hostile,))],
        )

    def test_second_row_is_a_cardinality_error_naming_the_bid(self):
        cursor = _ScriptedCursor([(1,), (2,)])
        with self.assertRaisesRegex(
            BidSettingsCardinalityError,
            r"^BidSettings has multiple rows for Bids\.UID=9; "
            r"expected at most one\.$",
        ):
            fetch_optional_bid_settings_row(cursor, 9, ("A",))
        self.assertEqual(cursor.fetch_count, 2)

    def test_cardinality_error_prints_a_str_bid_uid_without_quotes(self):
        # Production passes the bid UID as str; it must not be repr()'d.
        cursor = _ScriptedCursor([(1,), (2,)])
        with self.assertRaisesRegex(
            BidSettingsCardinalityError,
            r"^BidSettings has multiple rows for Bids\.UID=7; "
            r"expected at most one\.$",
        ):
            fetch_optional_bid_settings_row(cursor, "7", ("A",))

    def test_falsy_second_row_still_counts_as_a_duplicate(self):
        cursor = _ScriptedCursor([(1,), ()])
        with self.assertRaises(BidSettingsCardinalityError):
            fetch_optional_bid_settings_row(cursor, 9, ("A",))

    def test_falsy_single_row_is_returned_not_treated_as_missing(self):
        empty = ()
        cursor = _ScriptedCursor([empty])
        self.assertIs(fetch_optional_bid_settings_row(cursor, 9, ("A",)), empty)
        self.assertEqual(cursor.fetch_count, 2)

    def test_cardinality_error_is_a_runtime_error_subclass(self):
        self.assertTrue(issubclass(BidSettingsCardinalityError, RuntimeError))

    def test_execute_errors_propagate_without_fetching(self):
        cursor = _ScriptedCursor([(1,)], execute_error=OSError("disk gone"))
        with self.assertRaisesRegex(OSError, "disk gone"):
            fetch_optional_bid_settings_row(cursor, 9, ("A",))
        self.assertEqual(cursor.fetch_count, 0)

    def test_non_tuple_row_object_is_returned_by_identity(self):
        # Real pyodbc rows are not tuples: the row must come back untouched.
        row = object()
        cursor = _ScriptedCursor([row])
        self.assertIs(fetch_optional_bid_settings_row(cursor, 9, ("A",)), row)
