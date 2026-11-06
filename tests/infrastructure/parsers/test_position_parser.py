import unittest
from ost_visualizer.infrastructure.parsers import position_parser
from ost_visualizer.infrastructure.parsers.position_parser import (
    convert_elevation_in_name,
    extract_z_value_from_name,
)


class ElevationTextValidityCharacterizationTests(unittest.TestCase):
    def test_every_accepted_elevation_text_shape(self):
        accepted = (
            "745' 0\"",
            "12' 6 1/2\"",
            "12'-6\"",
            "5' 0\"",
            "5'x",
            '6"',
            '1/2"',
            '3 1/2"',
            "1m 20cm",
            "1m and 20cm",
            "1m+20cm",
            "2,5 m",
            "3 meters",
            "30 cm",
            "30 centimeters",
            "-4' 2\"",
        )
        for text in accepted:
            with self.subTest(text=text):
                self.assertTrue(position_parser._is_valid_elevation_text(text))

    def test_every_rejected_elevation_text_shape(self):
        rejected = (
            "",
            "later",
            "5pm",
            "abc 5'",
            "'",
            "m",
            "@T 5'",
            "5'",
            "-4'",
            "5' wall",
        )
        for text in rejected:
            with self.subTest(text=text):
                self.assertFalse(position_parser._is_valid_elevation_text(text))


class ExtractZValueCharacterizationTests(unittest.TestCase):
    def setUp(self):
        position_parser.clear_caches()
        self.addCleanup(position_parser.clear_caches)

    def test_top_and_bottom_imperial_values(self):
        self.assertEqual(extract_z_value_from_name("F9 @T 410' 3\""), (4923.0, True))
        self.assertEqual(extract_z_value_from_name("Wall @B 8' 0\""), (96.0, False))
        self.assertEqual(
            extract_z_value_from_name("Slab @T 12' 6 1/2\""), (150.5, True)
        )

    def test_metric_values_are_converted_to_inches(self):
        value, is_top = extract_z_value_from_name("Wall @T 2.54 m")
        self.assertTrue(is_top)
        self.assertAlmostEqual(value, 100.0, places=6)

    def test_names_without_a_valid_elevation_have_none(self):
        for name in ("", "Wall", "Wall @T later", "Wall @T 5pm", "Wall @T 5' 2 m"):
            with self.subTest(name=name):
                self.assertEqual(extract_z_value_from_name(name), (0.0, False))


class ConvertElevationInNameCharacterizationTests(unittest.TestCase):
    def test_imperial_to_metric_and_back(self):
        self.assertEqual(
            convert_elevation_in_name("Wall @B 8' 0\"", True), "Wall @B 243.84 cm"
        )
        self.assertEqual(
            convert_elevation_in_name("Wall @B 243.84 cm", False), "Wall @B 8' 0\""
        )

    def test_names_without_a_full_elevation_are_left_alone(self):
        for name in ("Wall", "Wall @T later", "Wall @T 5' junk"):
            with self.subTest(name=name):
                self.assertEqual(convert_elevation_in_name(name, True), name)



class FractionalInchesParsingTests(unittest.TestCase):
    parse = staticmethod(position_parser._parse_fractional_inches_text)

    def test_whole_fractional_and_mixed_inches(self):
        table = (
            ("6", 6.0),
            ("1/2", 0.5),
            ("3/4", 0.75),
            ("3 1/2", 3.5),
            ("3 3/4", 3.75),
            ("3 0.5", 3.5),
            ("  6 ", 6.0),
        )
        for text, expected in table:
            with self.subTest(text=text):
                value = self.parse(text)
                self.assertEqual(value, expected)
                self.assertIs(type(value), float)

    def test_a_leading_minus_negates_the_whole_value_including_its_fraction(self):
        table = (
            ("-6", -6.0),
            ("-12", -12.0),
            ("- 6", -6.0),
            ("-1/2", -0.5),
            ("-3 1/2", -3.5),
        )
        for text, expected in table:
            with self.subTest(text=text):
                self.assertEqual(self.parse(text), expected)

    def test_an_unreadable_whole_part_counts_as_zero(self):
        self.assertEqual(self.parse("x 1/2"), 0.5)
        self.assertEqual(self.parse("x 0.5"), 0.5)

    def test_unreadable_values_are_refused(self):
        for text in ("", "abc", "1/0x", "1/2/3"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    self.parse(text)


class ImperialElevationParsingTests(unittest.TestCase):
    parse = staticmethod(position_parser._parse_imperial_elevation)

    def test_feet_and_inches(self):
        table = (
            ("12' 6\"", 150.0),
            ("12' 6 1/2\"", 150.5),
            ("5\u2032 6\"", 66.0),
            ("0' 6\"", 6.0),
        )
        for text, expected in table:
            with self.subTest(text=text):
                self.assertEqual(self.parse(text), expected)

    def test_negative_feet_make_the_whole_elevation_negative(self):
        self.assertEqual(self.parse("-4' 2\""), -50.0)
        self.assertEqual(self.parse("-0' 6\""), -6.0)

    def test_feet_only(self):
        for text, expected in (("5'x", 60.0), ("5\u2032x", 60.0), ("-4'x", -48.0)):
            with self.subTest(text=text):
                value = self.parse(text)
                self.assertEqual(value, expected)
                self.assertIs(type(value), float)

    def test_inches_only(self):
        table = (
            ('6"', 6.0),
            ('-6"', -6.0),
            ('3 1/2"', 3.5),
            ('1/2"', 0.5),
        )
        for text, expected in table:
            with self.subTest(text=text):
                self.assertEqual(self.parse(text), expected)

    def test_unrecognised_text_is_zero(self):
        for text in ("garbage", "", "5"):
            with self.subTest(text=text):
                value = self.parse(text)
                self.assertEqual(value, 0.0)
                self.assertIs(type(value), float)


class MetricElevationParsingTests(unittest.TestCase):
    parse = staticmethod(position_parser._parse_metric_elevation)

    def test_every_metric_spelling_returns_centimetres(self):
        table = (
            ("1m 20cm", 120.0),
            ("1m and 20cm", 120.0),
            ("1m+20cm", 120.0),
            ("-1m 20cm", -80.0),
            ("2,5 m", 250.0),
            ("2.5m", 250.0),
            ("3 meters", 300.0),
            ("30 cm", 30.0),
            ("30 centimeters", 30.0),
        )
        for text, expected in table:
            with self.subTest(text=text):
                self.assertEqual(self.parse(text), expected)

    def test_unrecognised_text_is_zero(self):
        value = self.parse("junk")
        self.assertEqual(value, 0.0)
        self.assertIs(type(value), float)


class ElevationFormattingAndLookupTests(unittest.TestCase):
    def setUp(self):
        position_parser.clear_caches()
        self.addCleanup(position_parser.clear_caches)

    def test_whole_centimetres_print_without_decimals_and_others_with_two(self):
        self.assertEqual(position_parser._format_metric_elevation(50.0), "127 cm")
        self.assertEqual(position_parser._format_metric_elevation(96.0), "243.84 cm")
        self.assertEqual(position_parser._format_metric_elevation(0.0), "0 cm")

    def test_centimetres_become_inches(self):
        self.assertAlmostEqual(position_parser.cm_to_inches(254.0), 100.0)

    def test_every_valid_spelling_yields_inches_and_the_top_or_bottom_flag(self):
        table = (
            ("Wall @T 5'x", (60.0, True)),
            ("Wall @T 5\u2032x", (60.0, True)),
            ('Wall @B 6"', (6.0, False)),
            ("Wall @T 12' 6\"", (150.0, True)),
        )
        for name, expected in table:
            with self.subTest(name=name):
                self.assertEqual(extract_z_value_from_name(name), expected)
        value, is_top = extract_z_value_from_name("Wall @T 3 meters")
        self.assertTrue(is_top)
        self.assertAlmostEqual(value, 300.0 / 2.54)
        value, is_top = extract_z_value_from_name("Wall @B 30 cm")
        self.assertFalse(is_top)
        self.assertAlmostEqual(value, 30.0 / 2.54)

    def test_a_name_with_an_at_sign_but_no_elevation_has_none(self):
        for name in ("Wall @T ", "Wall @", "Wall @T"):
            with self.subTest(name=name):
                self.assertEqual(extract_z_value_from_name(name), (0.0, False))

    def test_a_missing_name_has_none_and_is_returned_unchanged_by_the_converter(self):
        self.assertEqual(extract_z_value_from_name(None), (0.0, False))
        self.assertIsNone(convert_elevation_in_name(None, True))
        self.assertEqual(convert_elevation_in_name("", True), "")

    def test_clearing_the_caches_empties_the_lookup_cache(self):
        extract_z_value_from_name("Wall @T 5'x")
        self.assertEqual(extract_z_value_from_name.cache_info().currsize, 1)
        position_parser.clear_caches()
        self.assertEqual(extract_z_value_from_name.cache_info().currsize, 0)

    def test_full_elevation_text_is_recognised_exactly(self):
        self.assertIs(position_parser._is_full_elevation_text("8' 0\""), True)
        self.assertIs(position_parser._is_full_elevation_text("243.84 cm"), True)
        self.assertIs(position_parser._is_full_elevation_text("Wall"), False)
        self.assertIs(position_parser._is_full_elevation_text("8' 0\" junk"), False)

    def test_conversion_handles_meters_and_leaves_partial_or_empty_results_alone(self):
        self.assertEqual(convert_elevation_in_name("Wall @T 3 meters", True), "Wall @T 300 cm")
        self.assertEqual(convert_elevation_in_name("Wall @T 5'x", True), "Wall @T 5'x")
        self.assertEqual(convert_elevation_in_name("Wall @T ", True), "Wall @T ")
        self.assertEqual(convert_elevation_in_name("Wall @T 0 cm", False), "Wall @T 0 cm")
        self.assertEqual(convert_elevation_in_name("Wall @B 6\"", True), "Wall @B 15.24 cm")
        self.assertEqual(convert_elevation_in_name("Wall @B 30 cm", True), "Wall @B 30 cm")
        self.assertEqual(
            convert_elevation_in_name("Wall @T 5\u2032 6\"", True), "Wall @T 167.64 cm"
        )


if __name__ == "__main__":
    unittest.main()
