import datetime
import decimal
import unittest
from ost_visualizer.infrastructure.parsers.ost_serializer import (
    serialize_row,
    serialize_value,
)


class OstSerializerRelationshipTests(unittest.TestCase):
    def test_ost_numeric_serializer_uses_reference_float_shape(self):
        self.assertEqual(serialize_value(0.0), "0")
        self.assertEqual(serialize_value(12.0), "12")
        self.assertEqual(serialize_value(2302.4439862543), "2302.443986254299944")
        self.assertEqual(serialize_value(-0.0), "0")
        self.assertEqual(serialize_value(-12.0), "-12")
        self.assertEqual(serialize_value(0.5), "0.5")
        self.assertEqual(serialize_value(1e15), "1000000000000000")

    def test_scalar_values_use_reference_text_shapes(self):
        self.assertEqual(serialize_value(None), "NULL")
        self.assertEqual(serialize_value(True), "1")
        self.assertEqual(serialize_value(False), "0")
        self.assertEqual(serialize_value(7), "7")
        self.assertEqual(serialize_value(decimal.Decimal("12.500")), "12.5")
        self.assertEqual(serialize_value(decimal.Decimal("12.000")), "12")
        self.assertEqual(
            serialize_value(datetime.datetime(2024, 3, 5, 7, 9, 11)),
            "2024 3 5 7 9 11",
        )
        self.assertEqual(serialize_value(b"a\x00b\x00"), "ab")

    def test_row_serialization_selects_text_encoding_per_table_and_column(self):
        description = [("Name", bytes), ("Notes", bytes)]
        latin1_name = b"caf\xe9"
        utf8_notes = "café".encode("utf-8")
        annotation_row = serialize_row(
            (latin1_name, utf8_notes), description, table="BidTexts"
        )
        self.assertEqual(annotation_row, {"Name": "café", "Notes": "café"})
        other_row = serialize_row(
            (utf8_notes, utf8_notes), description, table="BidConditions"
        )
        self.assertEqual(other_row, {"Name": "café", "Notes": "café"})
        with self.assertRaises(UnicodeDecodeError):
            serialize_row((latin1_name, utf8_notes), description, table="BidConditions")


class RawTextEncodingFailureTests(unittest.TestCase):
    def test_unknown_invalid_text_encoding_fails_instead_of_silently_losing_bytes(self):
        with self.assertRaises(UnicodeDecodeError):
            serialize_value(b"legacy\xff")
        with self.assertRaises(UnicodeDecodeError):
            serialize_row((b"legacy\xff",), [("Notes", bytes)], table="BidTexts")
