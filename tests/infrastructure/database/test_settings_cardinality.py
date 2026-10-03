import unittest
from ost_visualizer.infrastructure.database.settings_cardinality import (
    BidNumberAllocationUnavailableError,
    GlobalSettingsCardinalityError,
    fetch_optional_global_settings_row,
    normalize_next_bid_number,
    persist_next_bid_number,
    require_writable_bid_number_allocator,
)
from ost_visualizer.infrastructure.mdb.bid_settings_contract import (
    BidSettingsCardinalityError,
    fetch_optional_bid_settings_row,
)


class _RecordingCursor:
    def __init__(self, rows):
        self._rows = iter(rows)
        self.statements = []
        self.fetches = 0

    def execute(self, sql, *params):
        self.statements.append((sql, params))
        return self

    def fetchone(self):
        self.fetches += 1
        return next(self._rows, None)


class _SettingsSchema:
    def __init__(self, tables):
        self._tables = tables

    def optional_table_missing(self, table):
        return table not in self._tables

    def column_exists(self, table, column):
        return column in self._tables.get(table, ())


class GlobalSettingsCardinalityTests(unittest.TestCase):
    def test_zero_global_settings_rows_remain_valid(self):
        cursor = _RecordingCursor([])
        row = fetch_optional_global_settings_row(cursor, "[NextBidNo]")
        self.assertIsNone(row)
        self.assertEqual(
            cursor.statements,
            [("SELECT [NextBidNo] FROM [Settings]", ())],
        )

    def test_one_global_settings_row_is_returned(self):
        cursor = _RecordingCursor([(42,)])
        row = fetch_optional_global_settings_row(cursor, "[NextBidNo]")
        self.assertEqual(row, (42,))
        self.assertEqual(
            cursor.statements,
            [("SELECT [NextBidNo] FROM [Settings]", ())],
        )

    def test_duplicate_global_settings_rows_still_reject(self):
        cursor = _RecordingCursor([(42,), (43,)])
        with self.assertRaisesRegex(GlobalSettingsCardinalityError, "multiple rows"):
            fetch_optional_global_settings_row(cursor, "[NextBidNo]")
        self.assertEqual(len(cursor.statements), 1)

    def test_backend_table_reference_is_used_for_the_settings_read(self):
        cursor = _RecordingCursor([(5,)])
        row = fetch_optional_global_settings_row(
            cursor, "[NextBidNo]", table_sql="[dbo].[Settings] WITH (UPDLOCK)"
        )
        self.assertEqual(row, (5,))
        self.assertEqual(
            cursor.statements,
            [("SELECT [NextBidNo] FROM [dbo].[Settings] WITH (UPDLOCK)", ())],
        )

    def test_cardinality_probe_reads_at_most_one_row_past_the_first(self):
        for rows, expected_fetches, raises in (
            ([], 1, False),
            ([(1,)], 2, False),
            ([(1,), (2,), (3,)], 2, True),
        ):
            with self.subTest(rows=len(rows)):
                cursor = _RecordingCursor(rows)
                if raises:
                    with self.assertRaises(GlobalSettingsCardinalityError):
                        fetch_optional_global_settings_row(cursor, "[NextBidNo]")
                else:
                    fetch_optional_global_settings_row(cursor, "[NextBidNo]")
                self.assertEqual(cursor.fetches, expected_fetches)

    def test_the_multiple_row_message_names_the_settings_table(self):
        with self.assertRaisesRegex(
            GlobalSettingsCardinalityError,
            r"^Settings has multiple rows; expected at most one\.$",
        ):
            fetch_optional_global_settings_row(
                _RecordingCursor([(1,), (2,)]),
                "[NextBidNo]",
                table_sql="[dbo].[Settings] WITH (UPDLOCK, HOLDLOCK)",
            )


class BidNumberAllocationTests(unittest.TestCase):
    def test_empty_settings_table_is_initialized_and_present_row_is_updated(self):
        cursor = _RecordingCursor([])
        persist_next_bid_number(cursor, None, 8)
        persist_next_bid_number(cursor, (7,), 8, table_sql="[dbo].[Settings]")
        self.assertEqual(
            cursor.statements,
            [
                ("INSERT INTO [Settings] ([NextBidNo]) VALUES (?)", (8,)),
                ("UPDATE [dbo].[Settings] SET [NextBidNo] = ?", (8,)),
            ],
        )

    def test_next_bid_number_defaults_blank_and_zero_values_to_one(self):
        for value in (None, "", 0, "0"):
            with self.subTest(value=value):
                self.assertEqual(normalize_next_bid_number(value), 1)
        self.assertEqual(normalize_next_bid_number("12"), 12)
        self.assertEqual(normalize_next_bid_number(7), 7)

    def test_legacy_database_without_durable_allocator_is_rejected(self):
        require_writable_bid_number_allocator(
            _SettingsSchema({"Settings": {"NextBidNo"}})
        )
        with self.assertRaisesRegex(
            BidNumberAllocationUnavailableError, "Settings table is unavailable"
        ):
            require_writable_bid_number_allocator(_SettingsSchema({}))
        with self.assertRaisesRegex(
            BidNumberAllocationUnavailableError, "Settings.NextBidNo is unavailable"
        ):
            require_writable_bid_number_allocator(
                _SettingsSchema({"Settings": {"Other"}})
            )


class BidSettingsCardinalityTests(unittest.TestCase):
    """BidSettings is an optional singular row per bid on both backends."""

    def test_zero_rows_are_valid_and_one_row_is_returned(self):
        cursor = _RecordingCursor([])
        self.assertIsNone(fetch_optional_bid_settings_row(cursor, 5, ("A", "B")))
        self.assertEqual(
            cursor.statements,
            [("SELECT [A], [B] FROM [BidSettings] WHERE [BidUID]=?", (5,))],
        )
        self.assertEqual(cursor.fetches, 1)
        cursor = _RecordingCursor([(1, 2)])
        self.assertEqual(fetch_optional_bid_settings_row(cursor, "7", ("A",)), (1, 2))
        self.assertEqual(
            cursor.statements,
            [("SELECT [A] FROM [BidSettings] WHERE [BidUID]=?", ("7",))],
        )
        self.assertEqual(cursor.fetches, 2)

    def test_multiple_rows_for_one_bid_are_rejected_not_chosen(self):
        cursor = _RecordingCursor([(1,), (2,)])
        with self.assertRaisesRegex(
            BidSettingsCardinalityError,
            r"^BidSettings has multiple rows for Bids\.UID=5; "
            r"expected at most one\.$",
        ):
            fetch_optional_bid_settings_row(cursor, 5, ("A",))
        self.assertEqual(cursor.fetches, 2)
