import unittest
from ost_visualizer.infrastructure.mdb.reference_validation import (
    UID_NULL_VALUES,
    is_present_uid,
)


class IsPresentUidTests(unittest.TestCase):
    def test_empty_zero_and_null_text_are_absent_references(self):
        for value in ("", "0", "NULL"):
            with self.subTest(value=value):
                self.assertIs(is_present_uid(value), False)

    def test_any_other_text_is_a_present_reference(self):
        for value in ("1", "7", "999999999", "10", "-1", "x"):
            with self.subTest(value=value):
                self.assertIs(is_present_uid(value), True)

    def test_absence_matching_is_exact_and_case_sensitive(self):
        # Raw XML text is compared verbatim: near-misses count as present so
        # that malformed references reach the integrity validator.
        for value in ("00", "0.0", " 0", "0 ", "null", "Null", " ", "NULL "):
            with self.subTest(value=value):
                self.assertIs(is_present_uid(value), True)

    def test_null_value_set_is_exactly_the_three_documented_spellings(self):
        self.assertEqual(UID_NULL_VALUES, frozenset({"", "0", "NULL"}))
        self.assertIsInstance(UID_NULL_VALUES, frozenset)
