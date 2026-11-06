import unittest
import xml.etree.ElementTree as ET
from ost_visualizer.infrastructure.mdb.components.legend_position import (
    rescale_legend_position,
)


class RescaleLegendPositionInputTests(unittest.TestCase):
    def test_bytes_bytearray_and_str_inputs_give_identical_bytes_output(self):
        text = '<Legends dX="1" dY="2"><Legend dX="3" dY="4"/></Legends>'
        expected = b'<Legends dX="2" dY="4"><Legend dX="6" dY="8" /></Legends>'
        for label, value in (
            ("bytes", text.encode("latin-1")),
            ("bytearray", bytearray(text.encode("latin-1"))),
            ("str", text),
        ):
            with self.subTest(label):
                result = rescale_legend_position(value, 2.0)
                self.assertIs(type(result), bytes)
                self.assertEqual(result, expected)

    def test_position_text_uses_latin1_for_decode_and_encode(self):
        source = b'<Legends dX="1" Name="caf\xe9"/>'
        result = rescale_legend_position(source, 3.0)
        self.assertEqual(result, b'<Legends dX="3" Name="caf\xe9" />')
        self.assertEqual(
            rescale_legend_position(bytearray(source), 3.0),
            b'<Legends dX="3" Name="caf\xe9" />',
        )
        text_input = rescale_legend_position('<Legends Name="café"/>', 1.0)
        self.assertEqual(text_input, b'<Legends Name="caf\xe9" />')

    def test_non_legends_root_is_rejected_before_any_scaling(self):
        for source in (
            b'<Legend dX="1" dY="2"/>',
            b'<legends dX="1"/>',
            b'<Position dX="1"><Legends dX="1"/></Position>',
        ):
            with self.subTest(source=source):
                with self.assertRaisesRegex(
                    ValueError, r"^Legend Position requires a Legends XML root$"
                ):
                    rescale_legend_position(source, 2.0)

    def test_malformed_xml_raises_parse_error(self):
        for source in (b"", b"not xml", b'<Legends dX="1">'):
            with self.subTest(source=source):
                with self.assertRaises(ET.ParseError):
                    rescale_legend_position(source, 2.0)


class RescaleLegendPositionScalingTests(unittest.TestCase):
    def test_only_legends_and_legend_elements_are_scaled(self):
        source = (
            b'<Legends dX="10" dY="20" Custom="7">'
            b'<Legend dX="30" dY="40" FontSize="12"/>'
            b'<Extension dX="90" dY="91"/>'
            b'<legend dX="5" dY="6"/>'
            b"</Legends>"
        )
        result = rescale_legend_position(source, 0.5)
        self.assertEqual(
            result,
            b'<Legends dX="5" dY="10" Custom="7">'
            b'<Legend dX="15" dY="20" FontSize="12" />'
            b'<Extension dX="90" dY="91" />'
            b'<legend dX="5" dY="6" />'
            b"</Legends>",
        )

    def test_legend_elements_nested_below_other_elements_are_scaled(self):
        source = (
            b'<Legends><Group dX="1"><Legend dX="2" dY="3"/>'
            b'<Legends dX="4"/></Group></Legends>'
        )
        result = rescale_legend_position(source, 10.0)
        self.assertEqual(
            result,
            b'<Legends><Group dX="1"><Legend dX="20" dY="30" />'
            b'<Legends dX="40" /></Group></Legends>',
        )

    def test_missing_coordinates_are_not_invented(self):
        result = rescale_legend_position(
            b'<Legends dX="1"><Legend dY="2"/><Legend/></Legends>', 4.0
        )
        self.assertEqual(
            result, b'<Legends dX="4"><Legend dY="8" /><Legend /></Legends>'
        )
        self.assertEqual(rescale_legend_position(b"<Legends/>", 4.0), b"<Legends />")

    def test_x_and_y_are_scaled_independently_by_the_same_factor(self):
        result = rescale_legend_position(b'<Legends dX="7" dY="100"/>', 3.0)
        self.assertEqual(result, b'<Legends dX="21" dY="300" />')

    def test_scaled_values_use_three_decimals_without_trailing_zero_noise(self):
        cases = (
            ("100", 1.0, "100"),
            ("1.50", 1.0, "1.5"),
            ("10", 10.0, "100"),
            ("1.23456", 1.0, "1.235"),
            ("1.2344", 1.0, "1.234"),
            ("0.0004", 1.0, "0"),
            ("2.5", 0.4, "1"),
            ("1234.567", 0.3, "370.37"),
            ("2345.678", 0.3, "703.703"),
            ("-3", 2.0, "-6"),
            ("4", -0.5, "-2"),
            ("0", 5.0, "0"),
            ("1e2", 1.0, "100"),
        )
        for value, factor, expected in cases:
            with self.subTest(value=value, factor=factor):
                result = rescale_legend_position(
                    f'<Legends dX="{value}"/>'.encode("latin-1"), factor
                )
                self.assertEqual(result, f'<Legends dX="{expected}" />'.encode())

    def test_attribute_order_and_unrelated_attributes_are_preserved(self):
        result = rescale_legend_position(
            b'<Legends Z="1" dY="2" A="x" dX="3"/>', 2.0
        )
        self.assertEqual(result, b'<Legends Z="1" dY="4" A="x" dX="6" />')

    def test_comments_and_processing_instructions_survive_the_rewrite(self):
        source = (
            b'<Legends dX="1"><!--keep me--><?hint data?>'
            b'<Legend dX="2"><!--inner--></Legend></Legends>'
        )
        result = rescale_legend_position(source, 2.0)
        self.assertEqual(
            result,
            b'<Legends dX="2"><!--keep me--><?hint data?>'
            b'<Legend dX="4"><!--inner--></Legend></Legends>',
        )

    def test_text_and_tail_content_is_preserved(self):
        result = rescale_legend_position(
            b'<Legends dX="1">head<Legend dX="2">body</Legend>tail</Legends>', 2.0
        )
        self.assertEqual(
            result, b'<Legends dX="2">head<Legend dX="4">body</Legend>tail</Legends>'
        )


class RescaleLegendPositionFailureTests(unittest.TestCase):
    def test_non_finite_results_are_rejected_with_a_named_error(self):
        cases = (
            (b'<Legends dX="nan"/>', 2.0),
            (b'<Legends dX="inf"/>', 2.0),
            (b'<Legends dY="-inf"/>', 2.0),
            (b'<Legends dX="1e308"/>', 10.0),
            (b'<Legends dX="1"/>', float("inf")),
            (b'<Legends dX="1"/>', float("nan")),
            (b'<Legends><Legend dY="5"/></Legends>', float("inf")),
            (b'<Legends dX="inf"/>', 0.0),
        )
        for source, factor in cases:
            with self.subTest(source=source, factor=factor):
                with self.assertRaisesRegex(
                    ValueError, r"^Legend Position coordinates must be finite$"
                ):
                    rescale_legend_position(source, factor)

    def test_non_numeric_coordinates_raise_value_error(self):
        for source in (b'<Legends dX="abc"/>', b'<Legends><Legend dY=""/></Legends>'):
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, "could not convert"):
                    rescale_legend_position(source, 2.0)

    def test_zero_factor_collapses_coordinates_to_zero(self):
        result = rescale_legend_position(b'<Legends dX="5" dY="6"/>', 0.0)
        self.assertEqual(result, b'<Legends dX="0" dY="0" />')

    def test_failure_does_not_modify_a_bytearray_source(self):
        source = bytearray(b'<Legends dX="nan"/>')
        with self.assertRaises(ValueError):
            rescale_legend_position(source, 2.0)
        self.assertEqual(source, bytearray(b'<Legends dX="nan"/>'))
