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
