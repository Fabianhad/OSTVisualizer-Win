"""Custom calibration labels retain precision and reject invalid scale ratios."""

import unittest
from ost_visualizer.presentation.utils.scales import format_custom_scale


class FormatCustomScaleTests(unittest.TestCase):
    def test_invalid_nonpositive_and_nonfinite_values_have_no_label(self):
        for invalid in (None, "invalid", 0, -1, float("nan"), float("inf")):
            with self.subTest(invalid=invalid):
                self.assertEqual(format_custom_scale(invalid, 12), "")
                self.assertEqual(format_custom_scale(1, invalid), "")

    def test_architectural_foot_and_general_ratio_are_distinct(self):
        self.assertEqual(format_custom_scale(0.125, 12), '0.125" = 1\' 0"')
        self.assertEqual(format_custom_scale(1, 12 + 1e-10), '1" = 1\' 0"')
        self.assertEqual(format_custom_scale(1, 120), "1 : 120")
        self.assertEqual(format_custom_scale("1.25", "1000"), "1.25 : 1000")

    def test_small_custom_values_are_not_rounded_to_zero(self):
        self.assertEqual(
            format_custom_scale(0.000000123456789, 1), "1.23456789e-07 : 1"
        )

    def test_only_the_twelve_inch_ratio_uses_foot_notation(self):
        self.assertEqual(format_custom_scale(2, 12), '2" = 1\' 0"')
        self.assertEqual(format_custom_scale(1, 12.0000001), "1 : 12.0000001")
        self.assertEqual(format_custom_scale(1, 12.001), "1 : 12.001")
        self.assertEqual(format_custom_scale(1, 11.999), "1 : 11.999")
        self.assertEqual(format_custom_scale(1, 24), "1 : 24")

    def test_float_noise_is_trimmed_to_fifteen_significant_digits(self):
        self.assertEqual(format_custom_scale(0.1 + 0.2, 1), "0.3 : 1")
        self.assertEqual(format_custom_scale(1, 1.0), "1 : 1")
        self.assertEqual(format_custom_scale(1234567.5, 2), "1234567.5 : 2")
        # Sixteen-plus digit inputs are cut to exactly fifteen significant digits.
        self.assertEqual(
            format_custom_scale(0.123456789012345678, 1), "0.123456789012346 : 1"
        )
        self.assertEqual(
            format_custom_scale(1, 1234567.12345678912), "1 : 1234567.12345679"
        )
