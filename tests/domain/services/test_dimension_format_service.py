import unittest
from ost_visualizer.domain.services.dimension_format_service import (
    MM_PER_INCH,
    display_to_inches,
    display_to_mm,
    inches_to_display,
    inches_to_mm,
    mm_to_display,
    mm_to_inches,
)


class DimensionFormattingTests(unittest.TestCase):
    def test_valid_imperial_and_metric_dimensions_have_exact_semantics(self):
        self.assertEqual(MM_PER_INCH, 25.4)
        for inches, text in (
            (0, ""),
            (0.125, '1/8"'),
            (1.5, '1 1/2"'),
            (12, "1' 0\""),
            (-14.25, "-1' 2 1/4\""),
        ):
            with self.subTest(inches=inches):
                self.assertEqual(inches_to_display(inches), text)
                self.assertEqual(display_to_inches(text), inches)
        self.assertEqual(inches_to_mm(1), 25.4)
        self.assertEqual(mm_to_inches(25.4), 1)
        self.assertEqual(inches_to_display(1, metric=True), "25.4")
        self.assertEqual(display_to_inches("25.4 mm", metric=True), 1)
        self.assertEqual(display_to_mm("25.4 mm"), 25.4)
        self.assertEqual(mm_to_display(-12.5), "-12.5")

    def test_dimension_text_rejects_non_finite_values_before_formatting(self):
        for text in ("nan", "inf", "-inf", "Infinity", "-Infinity"):
            with self.subTest(text=text):
                self.assertIsNone(display_to_inches(text))
                self.assertIsNone(display_to_inches(text, metric=True))
                self.assertIsNone(display_to_mm(text))
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                self.assertEqual(inches_to_display(value), "")
                self.assertEqual(inches_to_display(value, metric=True), "")
                self.assertEqual(mm_to_display(value), "")
        self.assertIsNone(display_to_inches(f"{'9' * 5000}'"))
