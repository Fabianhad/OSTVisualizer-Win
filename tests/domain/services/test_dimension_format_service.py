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


class DimensionDisplayTableTests(unittest.TestCase):
    def test_every_eighth_has_its_fraction_text_below_one_inch(self):
        for eighths, text in enumerate(
            ("", '1/8"', '1/4"', '3/8"', '1/2"', '5/8"', '3/4"', '7/8"')
        ):
            with self.subTest(eighths=eighths):
                self.assertEqual(inches_to_display(eighths / 8), text)
                self.assertEqual(
                    inches_to_display(-eighths / 8), f"-{text}" if text else ""
                )

    def test_inches_and_feet_layouts_for_every_combination_of_parts(self):
        for inches, text in (
            (5, '5"'),
            (11, '11"'),
            (5.5, '5 1/2"'),
            (11.875, '11 7/8"'),
            (12.125, "1' 0 1/8\""),
            (12.0, "1' 0\""),
            (13, "1' 1\""),
            (13.375, "1' 1 3/8\""),
            (24, "2' 0\""),
            (100, "8' 4\""),
            (-5, '-5"'),
            (-5.5, '-5 1/2"'),
            (-13, "-1' 1\""),
            (-12.5, "-1' 0 1/2\""),
            (-12, "-1' 0\""),
        ):
            with self.subTest(inches=inches):
                self.assertEqual(inches_to_display(inches), text)

    def test_rounding_goes_to_the_nearest_eighth_and_can_carry_into_feet(self):
        self.assertEqual(inches_to_display(0.06), "")
        self.assertEqual(inches_to_display(0.07), '1/8"')
        self.assertEqual(inches_to_display(11.99), "1' 0\"")
        self.assertEqual(inches_to_display(-0.06), "")
        self.assertEqual(inches_to_display(-0.07), '-1/8"')
        self.assertEqual(inches_to_display(0.0), "")
        self.assertEqual(inches_to_display(-0.0), "")

    def test_metric_display_drops_a_trailing_zero_and_keeps_six_significant_digits(
        self,
    ):
        for mm, text in (
            (0.0, ""),
            (-0.0, ""),
            (5.0, "5"),
            (-5.0, "-5"),
            (25.4, "25.4"),
            (-12.5, "-12.5"),
            (0.5, "0.5"),
            (1234567.0, "1234567"),
            (0.000123, "0.000123"),
            (1.23456789, "1.23457"),
        ):
            with self.subTest(mm=mm):
                self.assertEqual(mm_to_display(mm), text)
        self.assertEqual(inches_to_display(2.0, metric=True), "50.8")
        self.assertEqual(inches_to_display(0.0, metric=True), "")
        self.assertEqual(inches_to_display(1.0, metric=False), '1"')


class DimensionParsingTableTests(unittest.TestCase):
    def test_every_supported_imperial_layout_parses_to_inches(self):
        for text, inches in (
            ("5", 5.0),
            ("5.5", 5.5),
            ('5"', 5.0),
            ('  5 " ', 5.0),
            ("-5", -5.0),
            ("- 5.25", -5.25),
            ("1/2", 0.5),
            ('1/8"', 0.125),
            ("-3/4", -0.75),
            ("2 1/2", 2.5),
            ('2 3/8"', 2.375),
            ("-2 5/8", -2.625),
            ("3'", 36.0),
            ("-3'", -36.0),
            ("0'", 0.0),
            ("3' 4", 40.0),
            ("3'4", 40.0),
            ("3'-4", 40.0),
            ("3' 4.5\"", 40.5),
            ("-3' 4", -40.0),
            ("3' 1/2", 36.5),
            ("3'1/2\"", 36.5),
            ("-3' 7/8", -36.875),
            ("1' 2 1/4\"", 14.25),
            ("1'-2 1/4", 14.25),
            ("-1' 2 3/4\"", -14.75),
            ("10' 11 7/8\"", 10 * 12 + 11.875),
        ):
            with self.subTest(text=text):
                self.assertEqual(display_to_inches(text), inches)

    def test_every_eighth_fraction_parses_in_each_fraction_layout(self):
        for numerator in range(1, 8):
            frac = numerator / 8
            text = f"{numerator}/8"
            reduced = {2: "1/4", 4: "1/2", 6: "3/4"}.get(numerator, text)
            if numerator in (2, 4, 6):
                text = reduced
            with self.subTest(fraction=text):
                self.assertEqual(display_to_inches(text), frac)
                self.assertEqual(display_to_inches(f"2 {text}"), 2 + frac)
                self.assertEqual(display_to_inches(f"2' {text}"), 24 + frac)
                self.assertEqual(display_to_inches(f"2' 3 {text}"), 27 + frac)
                self.assertEqual(display_to_inches(f"-2' 3 {text}"), -(27 + frac))
                self.assertEqual(display_to_inches(f"-{text}"), -frac)

    def test_blank_input_is_zero_and_plain_numbers_fall_back_to_float_parsing(self):
        for text in ("", "   ", "\t"):
            self.assertEqual(display_to_inches(text), 0.0)
            self.assertEqual(display_to_inches(text, metric=True), 0.0)
            self.assertEqual(display_to_mm(text), 0.0)
        self.assertEqual(display_to_inches("1e2"), 100.0)
        self.assertEqual(display_to_inches(".5"), 0.5)
        self.assertEqual(display_to_inches("+7"), 7.0)

    def test_unparseable_text_and_unsupported_fractions_are_rejected(self):
        for text in (
            "abc",
            "1/3",
            "2 1/3",
            "3' 1/3",
            "3' 2 1/3",
            "1/0",
            "3' 4 5",
            "3 ft",
            "1 2 3",
            "--5",
            "5'' 3",
            "3' 4 1/2 3",
        ):
            with self.subTest(text=text):
                self.assertIsNone(display_to_inches(text))
                self.assertIsNone(display_to_inches(text, metric=True))

    def test_trailing_text_after_every_layout_is_rejected_not_ignored(self):
        # Each parse layout is anchored at the end, so a complete layout followed by
        # junk must not be accepted as the leading part.
        layouts = {
            "feet inches fraction": ("3' 4 1/2", "x"),
            "feet inches": ("3' 4", "x"),
            "feet fraction": ("3' 1/2", "x"),
            "feet only": ("3'", "x"),
            "inches fraction": ("2 1/2", " junk"),
            "fraction only": ("1/2", "x"),
            "inches only": ("4", "x"),
        }
        for name, (valid, junk) in layouts.items():
            with self.subTest(layout=name):
                self.assertIsNotNone(display_to_inches(valid))
                self.assertIsNone(display_to_inches(valid + junk))
                self.assertIsNone(display_to_inches(valid + '" ' + junk.strip()))

    def test_overflowing_digit_runs_are_rejected_in_every_layout(self):
        huge = "9" * 5000
        for text in (
            f"{huge}'",
            f"{huge}' 3",
            f"3' {huge}",
            f"{huge}' 1/2",
            f"{huge}' 3 1/2",
            f"3' {huge} 1/2",
            f"{huge} 1/2",
            huge,
            f"-{huge}",
        ):
            with self.subTest(text=text[:12]):
                self.assertIsNone(display_to_inches(text))

    def test_metric_input_accepts_an_mm_suffix_with_any_case_and_spaces(self):
        for text, mm in (
            ("25.4", 25.4),
            ("25.4mm", 25.4),
            ("25.4 MM", 25.4),
            ("25.4 Mm", 25.4),
            ("  -3  m ", -3.0),
            ("1e1", 10.0),
        ):
            with self.subTest(text=text):
                self.assertEqual(display_to_mm(text), mm)
                self.assertAlmostEqual(display_to_inches(text, metric=True), mm / 25.4)
        self.assertIsNone(display_to_mm("12 cm"))
        self.assertIsNone(display_to_mm("mm mm x"))

    def test_display_and_parse_round_trip_every_eighth_up_to_three_feet(self):
        for eighths in range(0, 8 * 36 + 1):
            inches = eighths / 8
            with self.subTest(inches=inches):
                self.assertEqual(display_to_inches(inches_to_display(inches)), inches)
                self.assertEqual(display_to_inches(inches_to_display(-inches)), -inches)
        for mm in (0.0, 1.0, -7.5, 250.25):
            self.assertEqual(display_to_mm(mm_to_display(mm)), mm)
            self.assertAlmostEqual(
                display_to_inches(
                    inches_to_display(mm_to_inches(mm), metric=True), metric=True
                ),
                mm_to_inches(mm),
            )

    def test_unit_conversion_helpers_are_inverse_and_linear(self):
        self.assertAlmostEqual(mm_to_inches(50.8), 2.0)
        self.assertAlmostEqual(inches_to_mm(2.0), 50.8)
        self.assertEqual(mm_to_inches(0), 0)
        self.assertEqual(inches_to_mm(-1), -25.4)
        self.assertAlmostEqual(mm_to_inches(inches_to_mm(3.3)), 3.3)

    def test_only_a_trailing_m_unit_is_stripped_from_metric_text(self):
        for text in ("5X", "5x", "5 mX", "5 Xm X"):
            with self.subTest(text=text):
                self.assertIsNone(display_to_mm(text))
        self.assertEqual(display_to_mm("5mmm"), 5.0)
