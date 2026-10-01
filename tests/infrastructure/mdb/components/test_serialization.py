import math
import unittest
from ost_visualizer.infrastructure.database.annotation_storage import (
    ANNOTATION_TABLE_BY_TYPE,
)
from ost_visualizer.infrastructure.mdb.components.serialization import (
    TEXT_POSITION_TABLES,
    decode_annotation_text,
    encode_annotation_text,
    parse_position_storage,
    serialize_position_for_table,
)
from tests.helpers.annotation_geometry import ANNOTATION_POSITIONS


class PositionStorageSerializationTests(unittest.TestCase):
    def test_text_position_table_classification_includes_text_annotation_tables(self):
        self.assertEqual(
            TEXT_POSITION_TABLES,
            frozenset({"BidTexts", "BidCallOuts", "BidComments"}),
        )
        self.assertNotIn("BidTakeoffs", TEXT_POSITION_TABLES)
        self.assertNotIn("BidDimensions", TEXT_POSITION_TABLES)

    def test_position_serializer_returns_text_for_text_position_tables(self):
        position = [1.5, 2.25, 3.0, 4.125]
        for table, expected in (
            ("BidTexts", "1.5;2.25;3.0;4.125\n"),
            ("BidCallOuts", "1.5;2.25;3.0;4.125\n"),
            ("BidComments", "1.5;2.25;3;4.125\n"),
        ):
            with self.subTest(table=table):
                self.assertEqual(
                    serialize_position_for_table(table, position), expected
                )

    def test_position_serializer_returns_bytes_for_binary_position_tables(self):
        position = [1.5, 2.25, 3.0, 4.125]
        self.assertEqual(
            serialize_position_for_table("BidTakeoffs", position),
            b"1.5;2.25;3;4.125\n",
        )
        self.assertEqual(
            serialize_position_for_table("BidDimensions", position),
            b"1.5;2.25;3.0;4.125\n",
        )

    def test_position_serializer_rounds_non_annotation_tables_to_three_decimals(self):
        self.assertEqual(
            serialize_position_for_table("BidTakeoffs", [1.23456, 2.0, 0.5]),
            b"1.235;2;0.5\n",
        )
        self.assertEqual(
            serialize_position_for_table("BidComments", [1.23456, 2.0]),
            "1.235;2\n",
        )
        self.assertEqual(
            serialize_position_for_table("BidDimensions", [1.23456, 2.0]),
            b"1.23456;2.0\n",
        )

    def test_position_parser_reads_text_and_binary_storage_values(self):
        position = [1.0, 2.0, 3.0, 4.0]
        binary_value = serialize_position_for_table("BidTakeoffs", position)
        text_value = serialize_position_for_table("BidTexts", position)
        self.assertEqual(parse_position_storage(binary_value), position)
        self.assertEqual(parse_position_storage(text_value), position)
        self.assertEqual(parse_position_storage(b"1;2.5;-3\n"), [1.0, 2.5, -3.0])
        self.assertEqual(
            parse_position_storage(bytearray(b"1;2.5;-3\n")), [1.0, 2.5, -3.0]
        )
        self.assertEqual(parse_position_storage("1;2.5;-3\n"), [1.0, 2.5, -3.0])

    def test_position_parser_returns_no_geometry_for_empty_or_non_numeric_storage(self):
        for value in (None, "", b"", b"not-a-position", "1;x;3"):
            with self.subTest(value=value):
                self.assertEqual(parse_position_storage(value), [])

    def test_position_parsing_returns_independent_lists(self):
        first = parse_position_storage("1;2;3;4")
        first.append(5.0)
        self.assertEqual(parse_position_storage("1;2;3;4"), [1.0, 2.0, 3.0, 4.0])


class TextAnnotationStorageTests(unittest.TestCase):
    def test_legacy_text_encoding_rejects_unrepresentable_characters_without_replacement(
        self,
    ):
        for text in ("中文", "\U0001f600"):
            with self.subTest(text=text):
                with self.assertRaises(UnicodeEncodeError):
                    encode_annotation_text(text)

    def test_text_geometry_roundtrip_preserves_fractional_dimensions_and_rotation(self):
        position = [1 / 64, -1 / 25.4, 80.123456, 24.654321, math.pi / 7]
        self.assertEqual(
            parse_position_storage(serialize_position_for_table("BidTexts", position)),
            position,
        )

    def test_text_roundtrip_preserves_significant_whitespace(self):
        for text in ("", " \t ", "  indented\nsecond line  \n", "café 'quote'\tend "):
            with self.subTest(text=text):
                self.assertEqual(
                    decode_annotation_text(encode_annotation_text(text)), text
                )

    def test_text_uses_latin1_bytes_and_decoding_normalizes_crlf_and_nul(self):
        self.assertEqual(encode_annotation_text("café"), b"caf\xe9")
        self.assertEqual(decode_annotation_text(b"caf\xe9"), "café")
        self.assertEqual(decode_annotation_text(b"a\r\nb\x00c"), "a\nbc")


class DimensionLifecycleTests(unittest.TestCase):
    def test_dimension_fractional_roundtrip_does_not_quantize_model_geometry(self):
        for position in (
            [1 / 64, -1 / 25.4, 31 / 64, 2 / 25.4],
            [10.1234567, -100.7654321, 10000.1234567, -4.0123456],
        ):
            with self.subTest(position=position):
                self.assertEqual(
                    parse_position_storage(
                        serialize_position_for_table("BidDimensions", position)
                    ),
                    position,
                )


class AnnotationFamilyGeometryTests(unittest.TestCase):
    POSITIONS = ANNOTATION_POSITIONS

    def test_each_family_storage_preserves_fractional_geometry(self):
        self.assertEqual(set(self.POSITIONS), set(ANNOTATION_TABLE_BY_TYPE))
        for kind, position in self.POSITIONS.items():
            with self.subTest(kind=kind):
                stored = serialize_position_for_table(
                    ANNOTATION_TABLE_BY_TYPE[kind], position
                )
                self.assertEqual(parse_position_storage(stored), position)
