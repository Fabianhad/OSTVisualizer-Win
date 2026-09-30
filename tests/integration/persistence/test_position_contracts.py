import unittest
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.domain.utils.position import parse_position
from ost_visualizer.infrastructure.mdb.components.serialization import (
    TEXT_POSITION_TABLES,
    encode_position,
    parse_position_storage,
    serialize_position_for_table,
)


class PositionConsumerParityTests(unittest.TestCase):
    def test_position_parsing_has_one_value_contract_across_consumers(self):
        text = "1; 2;&#xA;3;4"
        expected = [1.0, 2.0, 3.0, 4.0]
        self.assertEqual(parse_position(text), expected)
        self.assertEqual(parse_position_storage(text), expected)
        self.assertEqual(OSTCoordinateSystem.parse_position(text), expected)

    def test_position_parsing_preserves_previous_text_edge_cases(self):
        cases = (
            (None, []),
            ("", []),
            ("   ", []),
            ("1;2;", [1.0, 2.0]),
            ("1;; 2 ;\n", [1.0, 2.0]),
            ("1;&#10;2;&#x0A;3;&#xA;4", [1.0, 2.0, 3.0, 4.0]),
            ("1;bad;3", []),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(parse_position(value), expected)
                self.assertEqual(OSTCoordinateSystem.parse_position(value), expected)

    def test_position_storage_preserves_binary_and_text_contracts(self):
        self.assertEqual(
            parse_position_storage(b"-1.5;0;2.25;4\n"),
            [-1.5, 0.0, 2.25, 4.0],
        )
        self.assertEqual(
            parse_position_storage(bytearray(b"1;2;3;4\n")),
            [1.0, 2.0, 3.0, 4.0],
        )
        self.assertEqual(OSTCoordinateSystem.parse_position((1, 2)), [1.0, 2.0])
