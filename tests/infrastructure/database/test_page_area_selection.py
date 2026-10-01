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
