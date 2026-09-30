import unittest
from ost_visualizer.infrastructure.parsers.ost_serializer import serialize_value
from ost_visualizer.infrastructure.parsers.ost_serializer import (
    serialize_row,
    serialize_value,
)


class OstSerializerRelationshipTests(unittest.TestCase):
    def test_ost_numeric_serializer_uses_reference_float_shape(self):
        self.assertEqual(serialize_value(0.0), "0")
        self.assertEqual(serialize_value(12.0), "12")
        self.assertEqual(serialize_value(2302.4439862543), "2302.443986254299944")


class RawTextEncodingFailureTests(unittest.TestCase):
    def test_unknown_invalid_text_encoding_fails_instead_of_silently_losing_bytes(self):
        with self.assertRaises(UnicodeDecodeError):
            serialize_value(b"legacy\xff")
