import unittest
from ost_visualizer.infrastructure.mdb.components.serialization import (
    TEXT_POSITION_TABLES,
    encode_position,
    parse_position_storage,
    serialize_position_for_table,
)
import math
from ost_visualizer.infrastructure.mdb.components.serialization import (
    decode_annotation_text,
    encode_annotation_text,
    parse_position_storage,
    serialize_position_for_table,
)
from PySide6 import QtCore, QtWidgets
from ost_visualizer.infrastructure.mdb.components.serialization import (
    serialize_position_for_table,
    parse_position_storage,
)
import tests.integration.placement.test_annotation_keyboard as qt_fixtures
from tests.integration.annotations.family_support import (
    _PlanFixture as _family_support__PlanFixture,
)
from tests.integration.annotations.family_support import (
    AnnotationFamilyGeometry as _family_support_AnnotationFamilyGeometry,
)


class PositionStorageSerializationTests(unittest.TestCase):
    def test_text_position_table_classification_includes_text_annotation_tables(self):
        self.assertIn("BidTexts", TEXT_POSITION_TABLES)
        self.assertIn("BidCallOuts", TEXT_POSITION_TABLES)
        self.assertIn("BidComments", TEXT_POSITION_TABLES)
        self.assertNotIn("BidTakeoffs", TEXT_POSITION_TABLES)

    def test_position_serializer_returns_text_for_text_position_tables(self):
        position = [1.0, 2.0, 3.0, 4.0]
        self.assertIsInstance(serialize_position_for_table("BidTexts", position), str)
        self.assertIsInstance(
            serialize_position_for_table("BidCallOuts", position), str
        )
        self.assertIsInstance(
            serialize_position_for_table("BidComments", position), str
        )

    def test_position_serializer_returns_bytes_for_binary_position_tables(self):
        value = serialize_position_for_table("BidTakeoffs", [1.0, 2.0, 3.0, 4.0])
        self.assertIsInstance(value, bytes)

    def test_position_parser_reads_text_and_binary_storage_values(self):
        position = [1.0, 2.0, 3.0, 4.0]
        binary_value = serialize_position_for_table("BidTakeoffs", position)
        text_value = serialize_position_for_table("BidTexts", position)
        self.assertEqual(parse_position_storage(binary_value), position)
        self.assertEqual(parse_position_storage(text_value), position)

    def test_position_parsing_returns_independent_lists(self):
        first = parse_position_storage("1;2;3;4")
        first.append(5.0)
        self.assertEqual(parse_position_storage("1;2;3;4"), [1.0, 2.0, 3.0, 4.0])


class TextAnnotationStorageTests(unittest.TestCase):
    def test_legacy_text_encoding_rejects_unrepresentable_characters_without_replacement(
        self,
    ):
        for text in ("\u4e2d\u6587", "\U0001f600"):
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


class DimensionLifecycleTests(_family_support__PlanFixture, unittest.TestCase):
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


class AnnotationFamilyGeometryTests(
    _family_support_AnnotationFamilyGeometry, unittest.TestCase
):
    def test_each_family_storage_preserves_fractional_geometry(self):
        from ost_visualizer.infrastructure.database.annotation_storage import (
            ANNOTATION_TABLE_BY_TYPE,
        )

        self.assertEqual(set(self.POSITIONS), set(ANNOTATION_TABLE_BY_TYPE))
        for kind, position in self.POSITIONS.items():
            with self.subTest(kind=kind):
                stored = serialize_position_for_table(
                    ANNOTATION_TABLE_BY_TYPE[kind], position
                )
                self.assertEqual(parse_position_storage(stored), position)
