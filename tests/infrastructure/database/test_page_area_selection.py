import unittest
from copy import deepcopy
from ost_visualizer.infrastructure.database.page_area_selection import (
    canonicalize_page_area_settings,
)


class CanonicalizePageAreaSettingsTests(unittest.TestCase):
    def test_highest_selection_rank_then_uid_wins_independently_per_page(self):
        rows = [
            {"UID": "10", "BidPageUID": "p1", "BidAreaSelected": 1},
            {"UID": "2", "BidPageUID": "p1", "BidAreaSelected": 2},
            {"UID": "11", "BidPageUID": "p1", "BidAreaSelected": 2},
            {"UID": "1", "BidPageUID": "p2", "BidAreaSelected": 1},
        ]
        before = deepcopy(rows)
        result = canonicalize_page_area_settings(rows)
        self.assertEqual(result, [rows[2], rows[3]])
        self.assertIs(result[0], rows[2])
        self.assertIs(result[1], rows[3])
        self.assertEqual(rows, before)

    def test_inactive_and_malformed_selections_are_preserved_in_input_order(self):
        rows = [
            {"UID": index, "BidAreaSelected": value}
            for index, value in enumerate((None, "bad", -1, 0, "0"))
        ]
        self.assertEqual(canonicalize_page_area_settings(rows), rows)
        self.assertEqual(canonicalize_page_area_settings([]), [])

    def test_equal_rank_uses_last_row_without_mutating_earlier_row(self):
        first = {
            "UID": "bad",
            "BidPageUID": "p1",
            "BidAreaSelected": "1",
            "AreaUID": "a",
        }
        last = {"UID": None, "BidPageUID": "p1", "BidAreaSelected": 1, "AreaUID": "b"}
        self.assertEqual(canonicalize_page_area_settings([first, last]), [last])
        self.assertEqual(first["AreaUID"], "a")

    def test_inactive_rows_stay_ahead_of_one_selected_row_per_page(self):
        inactive_zero = {"UID": 1, "BidPageUID": 5, "BidAreaSelected": 0}
        older_selection = {"UID": 2, "BidPageUID": 5, "BidAreaSelected": "1"}
        newer_selection = {"UID": 3, "BidPageUID": "5", "BidAreaSelected": 1}
        inactive_none = {"UID": 4, "BidPageUID": 5, "BidAreaSelected": None}
        other_page = {"UID": 5, "BidPageUID": 6, "BidAreaSelected": 1}
        result = canonicalize_page_area_settings(
            [inactive_zero, older_selection, newer_selection, inactive_none, other_page]
        )
        expected = [inactive_zero, inactive_none, newer_selection, other_page]
        self.assertEqual(result, expected)
        for expected_row, actual_row in zip(expected, result):
            self.assertIs(actual_row, expected_row)

    def test_higher_selection_rank_beats_a_later_higher_uid(self):
        ranked = {"UID": 1, "BidPageUID": "p1", "BidAreaSelected": 3}
        later = {"UID": 99, "BidPageUID": "p1", "BidAreaSelected": 2}
        self.assertEqual(canonicalize_page_area_settings([ranked, later]), [ranked])
        self.assertEqual(canonicalize_page_area_settings([later, ranked]), [ranked])

    def test_selected_rows_without_a_page_uid_share_one_group(self):
        missing = {"UID": 1, "BidPageUID": None, "BidAreaSelected": 1}
        blank = {"UID": 2, "BidPageUID": "", "BidAreaSelected": 1}
        absent = {"UID": 3, "BidAreaSelected": 1}
        other_page = {"UID": 4, "BidPageUID": "p1", "BidAreaSelected": 1}
        # None, "" and a missing key all normalise to the same empty page key,
        # so one selected row survives for them (the last of equal rank) while
        # a real page keeps its own.
        self.assertEqual(
            canonicalize_page_area_settings([missing, blank, absent, other_page]),
            [absent, other_page],
        )

    def test_zero_page_uid_means_no_page_and_joins_the_none_blank_and_missing_group(
        self,
    ):
        # Decision D11: a Page UID is a positive integer (Access COUNTER and SQL
        # IDENTITY(1,1) start at 1, the MDB reader and every write preflight reject
        # a BidPages UID of 0, the importer never maps a source UID of 0), so 0 is
        # the legacy spelling of "no page" and groups with None, "" and a missing
        # key. Equal rank means the last row of a group wins, which shows the
        # grouping: separate groups would both survive.
        no_page_spellings = {
            "none": {"BidPageUID": None},
            "blank": {"BidPageUID": ""},
            "missing": {},
            "int zero": {"BidPageUID": 0},
            "float zero": {"BidPageUID": 0.0},
        }
        for left_name, left_page in no_page_spellings.items():
            for right_name, right_page in no_page_spellings.items():
                with self.subTest(left=left_name, right=right_name):
                    left = {"UID": 1, "BidAreaSelected": 1, **left_page}
                    right = {"UID": 2, "BidAreaSelected": 1, **right_page}
                    result = canonicalize_page_area_settings([left, right])
                    self.assertEqual(len(result), 1)
                    self.assertIs(result[0], right)
        # A real page and the no-page group never merge, whatever the order.
        zero = {"UID": 1, "BidPageUID": 0, "BidAreaSelected": 1}
        real = {"UID": 2, "BidPageUID": 7, "BidAreaSelected": 1}
        self.assertEqual(canonicalize_page_area_settings([zero, real]), [zero, real])
        self.assertEqual(canonicalize_page_area_settings([real, zero]), [real, zero])

    def test_zero_page_uid_selection_rank_and_inactive_rows_follow_the_no_page_group(
        self,
    ):
        inactive_zero = {"UID": 1, "BidPageUID": 0, "BidAreaSelected": 0}
        inactive_none = {"UID": 2, "BidPageUID": None, "BidAreaSelected": None}
        low_zero = {"UID": 9, "BidPageUID": 0, "BidAreaSelected": 1}
        high_none = {"UID": 3, "BidPageUID": None, "BidAreaSelected": 2}
        result = canonicalize_page_area_settings(
            [low_zero, inactive_zero, high_none, inactive_none]
        )
        # Inactive rows are never grouped; the higher selection rank wins the
        # shared no-page group even though the other row has the higher UID.
        self.assertEqual(len(result), 3)
        self.assertIs(result[0], inactive_zero)
        self.assertIs(result[1], inactive_none)
        self.assertIs(result[2], high_none)

    def test_text_zero_page_uid_joins_the_no_page_group(self):
        # Decision D16 (replaces the D11 pin that kept "0" as its own group): the
        # text "0" is the same no-page group as int 0, "" and None. The importer
        # leaves "" untouched but rewrites "0" to "NULL"; text "0" itself is
        # normalised too so no spelling can add a second no-page selection.
        text_zero = {"UID": 1, "BidPageUID": "0", "BidAreaSelected": 1}
        int_zero = {"UID": 2, "BidPageUID": 0, "BidAreaSelected": 1}
        blank = {"UID": 3, "BidPageUID": "", "BidAreaSelected": 1}
        self.assertEqual(
            canonicalize_page_area_settings([text_zero, int_zero, blank]), [blank]
        )
        another_text_zero = {"UID": 4, "BidPageUID": "0", "BidAreaSelected": 1}
        self.assertEqual(
            canonicalize_page_area_settings([text_zero, another_text_zero]),
            [another_text_zero],
        )
        # A real page whose text merely contains a zero is never the no-page group.
        ten = {"UID": 5, "BidPageUID": "10", "BidAreaSelected": 1}
        zero_zero = {"UID": 6, "BidPageUID": "00", "BidAreaSelected": 1}
        self.assertEqual(
            canonicalize_page_area_settings([text_zero, ten, zero_zero]),
            [text_zero, ten, zero_zero],
        )

    def test_importer_null_placeholder_rows_collapse_into_one_group(self):
        # The OST importer rewrites a source page UID of "0" to the text "NULL"
        # before canonicalising, so selected rows that named no page share one
        # group; a real remapped page keeps its own row.
        first = {"UID": "1", "BidPageUID": "NULL", "BidAreaSelected": "1"}
        second = {"UID": "2", "BidPageUID": "NULL", "BidAreaSelected": "1"}
        real = {"UID": "3", "BidPageUID": "500", "BidAreaSelected": "1"}
        result = canonicalize_page_area_settings([first, second, real])
        self.assertEqual(len(result), 2)
        self.assertIs(result[0], second)
        self.assertIs(result[1], real)

    def test_blank_zero_and_null_placeholder_selections_leave_one_precedence_winner(
        self,
    ):
        # Decision D16: "", "0", the importer's "NULL" placeholder, None and a
        # missing key are ONE no-page group, so the canonical precedence
        # (BidAreaSelected DESC, UID DESC) leaves exactly one selected row for it,
        # whatever spelling and input order the rows have. Other pages and
        # inactive rows are untouched.
        spellings = ("", "0", "NULL", None, 0, 0.0, "missing")
        for winner_spelling in spellings:
            for loser_spelling in spellings:
                for order in (1, -1):
                    with self.subTest(
                        winner=winner_spelling, loser=loser_spelling, order=order
                    ):

                        def make(uid, selected, spelling):
                            row = {"UID": uid, "BidAreaSelected": selected}
                            if spelling != "missing":
                                row["BidPageUID"] = spelling
                            return row

                        winner = make("20", "2", winner_spelling)
                        loser = make("99", "1", loser_spelling)
                        real = {"UID": "40", "BidPageUID": "7", "BidAreaSelected": "1"}
                        inactive = {
                            "UID": "50",
                            "BidPageUID": "",
                            "BidAreaSelected": "0",
                        }
                        rows = [winner, loser][::order] + [real, inactive]
                        result = canonicalize_page_area_settings(rows)
                        # Selection rank beats the higher UID of the loser.
                        self.assertEqual(
                            [row["UID"] for row in result], ["50", "20", "40"]
                        )
                        self.assertIs(result[0], inactive)
                        self.assertIs(result[1], winner)
                        self.assertIs(result[2], real)

    def test_no_page_group_ties_on_rank_are_decided_by_uid_across_spellings(self):
        low = {"UID": "5", "BidPageUID": "", "BidAreaSelected": "1"}
        mid = {"UID": "6", "BidPageUID": "0", "BidAreaSelected": "1"}
        high = {"UID": "7", "BidPageUID": "NULL", "BidAreaSelected": "1"}
        for rows in ([low, mid, high], [high, low, mid], [mid, high, low]):
            with self.subTest(order=[row["UID"] for row in rows]):
                self.assertEqual(canonicalize_page_area_settings(rows), [high])
