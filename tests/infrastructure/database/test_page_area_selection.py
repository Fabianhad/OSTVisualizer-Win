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
