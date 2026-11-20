import datetime
import unittest
from decimal import Decimal
from ost_visualizer.domain.services.ost_text_values import (
    format_ost_datetime,
    format_ost_decimal,
    parse_ost_datetime,
)


class FormatOstDatetimeTests(unittest.TestCase):
    def test_datetime_is_six_unpadded_space_separated_fields(self):
        self.assertEqual(
            format_ost_datetime(datetime.datetime(2026, 11, 20, 8, 5, 0)),
            "2026 11 20 8 5 0",
        )
        self.assertEqual(
            format_ost_datetime(datetime.datetime(1999, 1, 2, 23, 59, 58, 999999)),
            "1999 1 2 23 59 58",
        )

    def test_date_is_written_as_midnight(self):
        self.assertEqual(
            format_ost_datetime(datetime.date(2026, 3, 4)), "2026 3 4 0 0 0"
        )


class ParseOstDatetimeTests(unittest.TestCase):
    def test_text_parses_back_to_the_same_second_precision_datetime(self):
        for value in (
            datetime.datetime(2026, 11, 20, 8, 30, 0),
            datetime.datetime(1900, 1, 1, 0, 0, 0),
            datetime.datetime(2026, 12, 31, 23, 59, 59),
        ):
            with self.subTest(value=value):
                self.assertEqual(parse_ost_datetime(format_ost_datetime(value)), value)

    def test_date_round_trips_as_its_midnight_datetime(self):
        self.assertEqual(
            parse_ost_datetime(format_ost_datetime(datetime.date(2026, 3, 4))),
            datetime.datetime(2026, 3, 4),
        )

    def test_malformed_or_impossible_text_is_none(self):
        for text in (
            None,
            "",
            "2026 11 20 8 30",
            "2026 11 20 8 30 0 0",
            "2026-11-20T08:30:00",
            "2026 13 20 8 30 0",
            "2026 2 30 8 30 0",
            "year 11 20 8 30 0",
            "99999999999999999999 1 1 0 0 0",
        ):
            with self.subTest(text=text):
                self.assertIsNone(parse_ost_datetime(text))


class FormatOstDecimalTests(unittest.TestCase):
    def test_integral_and_fractional_values_drop_trailing_zeros(self):
        self.assertEqual(format_ost_decimal(Decimal("12.000")), "12")
        self.assertEqual(format_ost_decimal(Decimal("-0.2500")), "-0.25")
        self.assertEqual(format_ost_decimal(Decimal("1E+2")), "100")
        self.assertEqual(format_ost_decimal(Decimal("0.0000001")), "0.0000001")

    def test_non_finite_values_are_rejected(self):
        for value in (Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as raised:
                    format_ost_decimal(value)
                self.assertEqual(
                    str(raised.exception),
                    f"Non-finite decimal value cannot be written: {value}",
                )


if __name__ == "__main__":
    unittest.main()
