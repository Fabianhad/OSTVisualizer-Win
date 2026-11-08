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

    def test_the_helper_tolerates_spaces_around_the_slash_of_a_mixed_number(self):
        # Characterisation of the private helper only: the elevation regexes never hand it
        # this shape, but the single split of the whole part keeps the fraction in one piece.
        self.assertEqual(self.parse("3 1 / 2"), 3.5)
        self.assertEqual(self.parse("-3 1 /2"), -3.5)

    def test_an_unreadable_whole_part_counts_as_zero(self):
        self.assertEqual(self.parse("x 1/2"), 0.5)
        self.assertEqual(self.parse("x 0.5"), 0.5)

    def test_unreadable_values_are_refused(self):
        for text in ("", "abc", "1/0x", "1/2/3"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    self.parse(text)

    def test_any_unicode_whitespace_separates_a_mixed_number_like_a_space(self):
        separators = {
            "space": " ",
            "no-break space": " ",
            "narrow no-break space": " ",
            "thin space": " ",
            "ideographic space": "　",
            "tab": "\t",
            "mixed": "   ",
        }
        for label, separator in separators.items():
            with self.subTest(separator=label):
                self.assertEqual(self.parse(f"3{separator}1/2"), 3.5)
                self.assertEqual(self.parse(f"3{separator}3/4"), 3.75)
                self.assertEqual(self.parse(f"-3{separator}1/2"), -3.5)
                self.assertEqual(self.parse(f"-{separator}3{separator}1/2"), -3.5)

    def test_unicode_whitespace_does_not_make_a_malformed_fraction_readable(self):
        for text in ("1 /2/3", "abc ", "1 1/0x", " "):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    self.parse(text)


class ZeroDenominatorElevationTests(unittest.TestCase):
    def setUp(self):
        position_parser.clear_caches()
        self.addCleanup(position_parser.clear_caches)

    def test_the_fraction_helper_refuses_a_zero_denominator_with_a_value_error(self):
        for text in ("1/0", "-1/0", "3 1/0", "-3 1/0", "3 1/00", "0/0", "3 1/0"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as caught:
                    position_parser._parse_fractional_inches_text(text)
                self.assertNotIsInstance(caught.exception, ZeroDivisionError)

    def test_a_zero_numerator_over_a_real_denominator_is_still_zero(self):
        self.assertEqual(position_parser._parse_fractional_inches_text("0/4"), 0.0)
        self.assertEqual(position_parser._parse_fractional_inches_text("3 0/4"), 3.0)

    def test_extracting_an_elevation_with_a_zero_denominator_is_a_value_error(self):
        for name in ('Wall @B 1/0"', 'Slab @T 6 1/0"', "Slab @T 12' 6 1/0\""):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    extract_z_value_from_name(name)

    def test_converting_an_elevation_with_a_zero_denominator_is_a_value_error(self):
        for metric in (True, False):
            with self.subTest(metric=metric):
                with self.assertRaises(ValueError):
                    convert_elevation_in_name('Wall @B 1/0"', metric)

    def test_a_failed_lookup_is_not_cached_and_valid_names_are_unaffected(self):
        with self.assertRaises(ValueError):
            extract_z_value_from_name('Wall @B 1/0"')
        with self.assertRaises(ValueError):
            extract_z_value_from_name('Wall @B 1/0"')
        self.assertEqual(extract_z_value_from_name('Wall @B 6 1/2"'), (6.5, False))


class UnicodeWhitespaceInElevationNameTests(unittest.TestCase):
    def setUp(self):
        position_parser.clear_caches()
        self.addCleanup(position_parser.clear_caches)

    def test_a_non_ascii_space_in_a_mixed_inch_value_reads_like_a_plain_space(self):
        for label, separator in (
            ("nbsp", " "),
            ("narrow nbsp", " "),
            ("tab", "\t"),
        ):
            with self.subTest(separator=label):
                self.assertEqual(
                    extract_z_value_from_name(f'Wall @B 6{separator}1/2"'), (6.5, False)
                )
                self.assertEqual(
                    extract_z_value_from_name(
                        f"Slab @T 12'{separator}6{separator}1/2\""
                    ),
                    (150.5, True),
                )
                self.assertEqual(
                    extract_z_value_from_name(f'Wall @B -6{separator}1/2"'),
                    (-6.5, False),
                )

    def test_a_non_ascii_space_does_not_change_the_converted_name(self):
        plain = convert_elevation_in_name('Wall @B 6 1/2"', True)
        for separator in (" ", " "):
            with self.subTest(separator=repr(separator)):
                self.assertEqual(
                    convert_elevation_in_name(f'Wall @B 6{separator}1/2"', True), plain
                )


class ImperialElevationParsingTests(unittest.TestCase):
    parse = staticmethod(position_parser._parse_imperial_elevation)

    def test_feet_and_inches(self):
        table = (
            ("12' 6\"", 150.0),
            ("12' 6 1/2\"", 150.5),
            ('5\u2032 6"', 66.0),
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
            ("-1m 20cm", -120.0),
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
        self.assertEqual(
            convert_elevation_in_name("Wall @T 3 meters", True), "Wall @T 300 cm"
        )
        self.assertEqual(convert_elevation_in_name("Wall @T 5'x", True), "Wall @T 5'x")
        self.assertEqual(convert_elevation_in_name("Wall @T ", True), "Wall @T ")
        self.assertEqual(
            convert_elevation_in_name("Wall @T 0 cm", False), "Wall @T 0 cm"
        )
        self.assertEqual(
            convert_elevation_in_name('Wall @B 6"', True), "Wall @B 15.24 cm"
        )
        self.assertEqual(
            convert_elevation_in_name("Wall @B 30 cm", True), "Wall @B 30 cm"
        )
        self.assertEqual(
            convert_elevation_in_name('Wall @T 5\u2032 6"', True), "Wall @T 167.64 cm"
        )


class MixedUnitAndCacheTests(unittest.TestCase):
    def setUp(self):
        position_parser.clear_caches()
        self.addCleanup(position_parser.clear_caches)

    def test_text_that_starts_like_one_unit_but_carries_the_other_has_no_elevation(
        self,
    ):
        # The prefix-matching validity gate accepts these (a quote or an m starts a valid
        # elevation), so only the unit check rejects them.
        for tail in ("5'cm", "5′cm", "5'm", '6"m', "5m'", "3 meters'"):
            with self.subTest(tail=tail):
                self.assertTrue(position_parser._is_valid_elevation_text(tail))
                self.assertEqual(
                    extract_z_value_from_name("Wall @T " + tail), (0.0, False)
                )
                self.assertEqual(
                    extract_z_value_from_name("Wall @B " + tail), (0.0, False)
                )
                self.assertEqual(
                    convert_elevation_in_name("Wall @T " + tail, True),
                    "Wall @T " + tail,
                )
                self.assertEqual(
                    convert_elevation_in_name("Wall @T " + tail, False),
                    "Wall @T " + tail,
                )

    def test_the_lookup_cache_is_bounded_to_2048_entries(self):
        for index in range(2100):
            extract_z_value_from_name(f"Wall {index} @T 5'x")
        info = extract_z_value_from_name.cache_info()
        self.assertEqual((info.currsize, info.maxsize), (2048, 2048))

    def test_a_repeated_lookup_is_served_from_the_cache(self):
        extract_z_value_from_name("Wall @T 5'x")
        extract_z_value_from_name("Wall @T 5'x")
        info = extract_z_value_from_name.cache_info()
        self.assertEqual((info.hits, info.misses), (1, 1))


# Every character str.split() and the regex \s treat as whitespace. They are written as
# \u escapes, never as raw characters, so the source shows what is being tested.
# U+200B (zero width space) is deliberately not in this set.
_UNICODE_SEPARATORS = {
    "ascii space": " ",
    "no-break space": "\u00a0",
    "narrow no-break space": "\u202f",
    "thin space": "\u2009",
    "figure space": "\u2007",
    "em space": "\u2003",
    "ideographic space": "\u3000",
    "tab": "\t",
    "vertical tab": "\x0b",
    "line feed": "\n",
    "next line": "\x85",
    "two mixed": "\u00a0\u202f",
}


class UnicodeWhitespaceBoundaryTests(unittest.TestCase):
    def setUp(self):
        position_parser.clear_caches()
        self.addCleanup(position_parser.clear_caches)

    def test_every_unicode_whitespace_separates_inch_fractions_in_both_entry_points(
        self,
    ):
        plain_metric = convert_elevation_in_name('Wall @B 6 1/2"', True)
        plain_imperial = convert_elevation_in_name('Wall @B 6 1/2"', False)
        self.assertEqual(plain_metric, "Wall @B 16.51 cm")
        self.assertEqual(plain_imperial, 'Wall @B 6 1/2"')
        for label, sep in _UNICODE_SEPARATORS.items():
            with self.subTest(separator=label):
                self.assertEqual(
                    extract_z_value_from_name(f'Wall @B 6{sep}1/2"'), (6.5, False)
                )
                self.assertEqual(
                    extract_z_value_from_name(f'Wall @T -6{sep}1/2"'), (-6.5, True)
                )
                self.assertEqual(
                    extract_z_value_from_name(f"Slab @T 12'{sep}6{sep}1/2\""),
                    (150.5, True),
                )
                self.assertEqual(
                    extract_z_value_from_name(f"Slab @T 12'{sep}6\""), (150.0, True)
                )
                self.assertEqual(
                    convert_elevation_in_name(f'Wall @B 6{sep}1/2"', True),
                    plain_metric,
                )
                self.assertEqual(
                    convert_elevation_in_name(f'Wall @B 6{sep}1/2"', False),
                    plain_imperial,
                )

    def test_a_run_of_mixed_whitespace_is_one_separator(self):
        mixed = " \u00a0\t\u202f "
        self.assertEqual(
            extract_z_value_from_name(f"Slab @T 12'{mixed}6{mixed}1/2\""),
            (150.5, True),
        )
        self.assertEqual(
            position_parser._parse_fractional_inches_text(f"-{mixed}3{mixed}3/4"), -3.75
        )

    def test_whitespace_around_the_fraction_bar_is_not_an_elevation(self):
        # The elevation grammar needs digits/digits; no whitespace flavour may bridge it,
        # and the converter must then leave the name alone instead of guessing.
        for label, sep in _UNICODE_SEPARATORS.items():
            for text in (f'6 1{sep}/2"', f'6 1/{sep}2"'):
                with self.subTest(separator=label, text=text):
                    name = "Wall @B " + text
                    self.assertEqual(extract_z_value_from_name(name), (0.0, False))
                    self.assertEqual(convert_elevation_in_name(name, True), name)
                    self.assertEqual(convert_elevation_in_name(name, False), name)

    def test_a_zero_width_space_is_not_whitespace(self):
        zwsp = "\u200b"
        for text in (f'6{zwsp}1/2"', f"12'{zwsp}6\""):
            with self.subTest(text=text):
                name = "Wall @B " + text
                self.assertEqual(extract_z_value_from_name(name), (0.0, False))
                self.assertEqual(convert_elevation_in_name(name, True), name)

    def test_whitespace_around_the_whole_value_is_ignored(self):
        for label, sep in _UNICODE_SEPARATORS.items():
            with self.subTest(separator=label):
                self.assertEqual(
                    extract_z_value_from_name(f'Wall @B{sep}6 1/2"{sep}'), (6.5, False)
                )

    def test_zero_denominators_stay_value_errors_with_any_whitespace_flavour(self):
        for label, sep in _UNICODE_SEPARATORS.items():
            for text in (f'6{sep}1/0"', f"12'{sep}6{sep}1/0\"", f'-6{sep}0/0"'):
                with self.subTest(separator=label, text=text):
                    with self.assertRaises(ValueError):
                        extract_z_value_from_name("Wall @B " + text)
                    with self.assertRaises(ValueError):
                        convert_elevation_in_name("Wall @B " + text, True)
                    with self.assertRaises(ValueError):
                        convert_elevation_in_name("Wall @B " + text, False)


class ElevationValueBoundaryTests(unittest.TestCase):
    def setUp(self):
        position_parser.clear_caches()
        self.addCleanup(position_parser.clear_caches)

    def test_a_dash_between_feet_and_inches_is_a_separator_not_a_sign(self):
        table = (
            ("Wall @T 12'-6\"", (150.0, True)),
            ("Wall @T 12' - 6\"", (150.0, True)),
            ("Wall @T 12'6\"", (150.0, True)),
            ("Wall @T -12'-6\"", (-150.0, True)),
            ("Wall @B 12'-6 1/2\"", (150.5, False)),
        )
        for name, expected in table:
            with self.subTest(name=name):
                self.assertEqual(extract_z_value_from_name(name), expected)
        self.assertEqual(
            convert_elevation_in_name("Wall @T 12'-6\"", False), "Wall @T 12' 6\""
        )
        self.assertEqual(
            convert_elevation_in_name("Wall @T 12'-6\"", True), "Wall @T 381 cm"
        )

    def test_zero_and_negative_values_keep_their_top_or_bottom_flag(self):
        table = (
            ('Wall @T 0"', (0.0, True)),
            ('Wall @B 0"', (0.0, False)),
            ("Wall @T 0' 0\"", (0.0, True)),
            ("Wall @T 0'x", (0.0, True)),
            ("Wall @T 0 cm", (0.0, True)),
            ('Wall @B 0/4"', (0.0, False)),
            ('Wall @T -1/2"', (-0.5, True)),
            ('Wall @B - 6"', (-6.0, False)),
            ("Wall @T 5' 6 0/4\"", (66.0, True)),
        )
        for name, expected in table:
            with self.subTest(name=name):
                self.assertEqual(extract_z_value_from_name(name), expected)
        self.assertEqual(
            convert_elevation_in_name('Wall @B 0/4"', True), "Wall @B 0 cm"
        )
        self.assertEqual(
            convert_elevation_in_name("Wall @T 0' 0\"", True), "Wall @T 0 cm"
        )
        self.assertEqual(
            convert_elevation_in_name('Wall @B -1/2"', True), "Wall @B -1.27 cm"
        )

    def test_a_zero_denominator_after_feet_without_whole_inches_is_not_an_elevation(
        self,
    ):
        # Feet plus a bare fraction is outside the grammar, so the zero denominator is
        # never reached: no exception, no elevation, name unchanged.
        for name in ("Wall @T 5' 1/0\"", "Wall @T 5' 1/2\""):
            with self.subTest(name=name):
                self.assertEqual(extract_z_value_from_name(name), (0.0, False))
                self.assertEqual(convert_elevation_in_name(name, True), name)
                self.assertEqual(convert_elevation_in_name(name, False), name)

    def test_the_zero_denominator_error_names_the_offending_fraction(self):
        for name, fragment in (
            ('Wall @B 1/0"', "1/0"),
            ('Wall @B 6 1/00"', "1/00"),
            ("Wall @T 12' 6 3/0\"", "3/0"),
            ('Wall @B 0/0"', "0/0"),
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    ValueError, rf"^zero denominator in fraction {fragment}$"
                ):
                    extract_z_value_from_name(name)
                with self.assertRaisesRegex(
                    ValueError, rf"^zero denominator in fraction {fragment}$"
                ):
                    convert_elevation_in_name(name, True)

    def test_a_denominator_that_is_zero_by_value_is_refused(self):
        for text in ("1/0.0", "1/-0", "1/0e0", "3 1/0.0"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as caught:
                    position_parser._parse_fractional_inches_text(text)
                self.assertNotIsInstance(caught.exception, ZeroDivisionError)
                self.assertIn("zero denominator", str(caught.exception))

    def test_only_a_zero_denominator_is_refused_not_a_negative_one(self):
        # Helper-level characterisation: the elevation grammar never yields a signed
        # denominator, but "zero" must mean the value 0, not "non-positive".
        self.assertEqual(position_parser._parse_fractional_inches_text("1/-1"), -1.0)
        self.assertEqual(position_parser._parse_fractional_inches_text("-1/-4"), 0.25)

    def test_a_very_large_denominator_gives_a_tiny_value_not_zero_or_an_error(self):
        self.assertEqual(
            extract_z_value_from_name('Wall @B 1/99999999999999999999"'), (1e-20, False)
        )
        self.assertEqual(
            position_parser._parse_fractional_inches_text("1/1000000"), 1e-06
        )

    def test_very_large_values_are_exact_or_float_rounded_not_rejected(self):
        self.assertEqual(
            extract_z_value_from_name("Wall @T 1000000000' 6\""),
            (12000000006.0, True),
        )
        self.assertEqual(
            extract_z_value_from_name("Wall @T -1000000000' 6\""),
            (-12000000006.0, True),
        )
        self.assertEqual(
            extract_z_value_from_name("Wall @T 99999999999999999999' 0\""),
            (1.2e21, True),
        )
        self.assertEqual(
            extract_z_value_from_name('Wall @B 99999999999999999999/1"'), (1e20, False)
        )

    def test_the_last_elevation_marker_wins_and_a_legacy_bare_marker_is_a_bottom(self):
        table = (
            ("Wall @T 5' 6\" @B 3' 0\"", (36.0, False)),
            ("Wall @B 3' 0\" @T 5' 6\"", (66.0, True)),
            ('A @T 1/2" @T 3/4"', (0.75, True)),
            ('Wall @ 6"', (6.0, False)),
            ('Wall @ 6 1/2"', (6.5, False)),
        )
        for name, expected in table:
            with self.subTest(name=name):
                self.assertEqual(extract_z_value_from_name(name), expected)
        self.assertEqual(
            convert_elevation_in_name('Wall @ 6"', True), "Wall @B 15.24 cm"
        )
        self.assertEqual(
            convert_elevation_in_name("Wall @T 5' 6\" @B 3' 0\"", True),
            "Wall @T 5' 6\" @B 91.44 cm",
        )

    def test_decimal_inches_and_nested_fractions_are_outside_the_grammar(self):
        for name in ('Wall @B 6.5"', 'Wall @T 6 1/2/3"', 'Wall @B 6 1/2/3"'):
            with self.subTest(name=name):
                self.assertEqual(extract_z_value_from_name(name), (0.0, False))
                self.assertEqual(convert_elevation_in_name(name, True), name)


class MetricSpellingBoundaryTests(unittest.TestCase):
    def setUp(self):
        position_parser.clear_caches()
        self.addCleanup(position_parser.clear_caches)

    def test_metric_units_are_case_insensitive_in_every_entry_point(self):
        table = (
            ("Wall @T 3 M", 300.0, True),
            ("Wall @B 30 CM", 30.0, False),
            ("Wall @T 1M 20CM", 120.0, True),
            ("Wall @B 3 Meters", 300.0, False),
            ("Wall @T 2 CENTIMETERS", 2.0, True),
        )
        for name, centimetres, is_top in table:
            with self.subTest(name=name):
                value, top = extract_z_value_from_name(name)
                self.assertAlmostEqual(value, centimetres / 2.54, places=9)
                self.assertIs(top, is_top)
        self.assertEqual(
            convert_elevation_in_name("Wall @T 3 M", True), "Wall @T 300 cm"
        )
        self.assertEqual(
            convert_elevation_in_name("Wall @B 3 Meters", False), "Wall @B 9' 10 1/8\""
        )
        for text, expected in (("1M 20CM", 120.0), ("3 METERS", 300.0), ("5 Cm", 5.0)):
            with self.subTest(helper=text):
                self.assertEqual(
                    position_parser._parse_metric_elevation(text), expected
                )

    def test_decimal_metres_and_decimal_centimetres_in_a_compound_value(self):
        table = (
            ("Wall @T 1.5m 20cm", 170.0),
            ("Wall @T 1,5 m 20 cm", 170.0),
            ("Wall @T 1m 2.5cm", 102.5),
            ("Wall @T 1m and 2,5 cm", 102.5),
        )
        for name, centimetres in table:
            with self.subTest(name=name):
                self.assertAlmostEqual(
                    extract_z_value_from_name(name)[0], centimetres / 2.54, places=9
                )
        self.assertEqual(position_parser._parse_metric_elevation("1.5m 20cm"), 170.0)
        self.assertEqual(position_parser._parse_metric_elevation("1m 2.5cm"), 102.5)

    def test_whitespace_around_the_value_is_ignored_by_both_entry_points(self):
        self.assertEqual(extract_z_value_from_name('Wall @T  -6"'), (-6.0, True))
        self.assertEqual(
            convert_elevation_in_name('Wall @T  -6"', True), "Wall @T -15.24 cm"
        )
        self.assertEqual(
            convert_elevation_in_name('Wall @T 6" ', True), "Wall @T 15.24 cm"
        )
        self.assertEqual(convert_elevation_in_name('Wall @T 6"  ', False), 'Wall @T 6"')

    def test_a_value_that_differs_from_whole_centimetres_by_a_hundredth_keeps_two_decimals(
        self,
    ):
        fmt = position_parser._format_metric_elevation
        self.assertEqual(fmt(1.006 / 2.54), "1.01 cm")
        self.assertEqual(fmt(0.994 / 2.54), "0.99 cm")
        self.assertEqual(fmt(-50.0), "-127 cm")
        self.assertEqual(fmt(-2.5 / 2.54), "-2.50 cm")


class PrivateParserSearchSemanticsTests(unittest.TestCase):
    """Characterisation of the private parsers' search (not anchored match) behaviour."""

    imperial = staticmethod(position_parser._parse_imperial_elevation)
    metric = staticmethod(position_parser._parse_metric_elevation)

    def test_a_foot_mark_needs_a_word_boundary_after_it(self):
        self.assertEqual(self.imperial("5'"), 0.0)
        self.assertEqual(self.imperial("5' x"), 0.0)
        self.assertEqual(self.imperial("5'x"), 60.0)

    def test_the_value_is_found_after_leading_noise(self):
        self.assertEqual(self.imperial("x5' 6\""), 66.0)
        self.assertEqual(self.imperial("x5'6"), 60.0)
        self.assertEqual(self.imperial('x 6"'), 6.0)
        self.assertEqual(self.metric("x 3 m"), 300.0)
        self.assertEqual(self.metric("x 30 cm"), 30.0)
        self.assertEqual(self.metric("x 1m 20cm"), 120.0)

    def test_the_fraction_helper_reads_decimal_parts_and_tiny_denominators(self):
        parse = position_parser._parse_fractional_inches_text
        self.assertEqual(parse("1.5/2"), 0.75)
        self.assertEqual(parse("6.5 1/2"), 7.0)
        self.assertEqual(parse("1/0.0000001"), 1e7)
        self.assertEqual(parse("1/1e-12"), 1e12)


class CompoundMetricConversionAndEmptyBaseNameTests(unittest.TestCase):
    def setUp(self):
        position_parser.clear_caches()
        self.addCleanup(position_parser.clear_caches)

    def test_compound_metric_values_convert_in_both_directions(self):
        table = (
            ("Wall @T 1m 20cm", "Wall @T 120 cm", "Wall @T 3' 11 1/4\""),
            ("Wall @T 1m and 20cm", "Wall @T 120 cm", "Wall @T 3' 11 1/4\""),
            ("Wall @B 1m+20cm", "Wall @B 120 cm", "Wall @B 3' 11 1/4\""),
            ("Wall @T -1m 20cm", "Wall @T -120 cm", "Wall @T -3' 11 1/4\""),
            ("Wall @T 1.5m 20cm", "Wall @T 170 cm", "Wall @T 5' 6 7/8\""),
        )
        for name, metric, imperial in table:
            with self.subTest(name=name):
                self.assertEqual(convert_elevation_in_name(name, True), metric)
                self.assertEqual(convert_elevation_in_name(name, False), imperial)

    def test_an_elevation_marker_with_an_empty_base_name_still_has_an_elevation(self):
        self.assertEqual(extract_z_value_from_name(' @T 6"'), (6.0, True))
        self.assertEqual(extract_z_value_from_name(' @B 6"'), (6.0, False))
        self.assertEqual(extract_z_value_from_name('   @T 6"'), (6.0, True))
        self.assertEqual(convert_elevation_in_name(' @B 6"', True), " @B 15.24 cm")
        self.assertEqual(convert_elevation_in_name(' @B 6"', False), ' @B 6"')

    def test_a_marker_without_the_leading_space_is_not_an_elevation_marker(self):
        self.assertEqual(extract_z_value_from_name('@T 6"'), (0.0, False))
        self.assertEqual(convert_elevation_in_name('@T 6"', True), '@T 6"')


class DetachedMinusTests(unittest.TestCase):
    """A minus separated from the number by spaces still negates the whole value.
    The elevation grammar (elevation_text) accepts ``-`` followed by whitespace, and an
    attached minus (``-5' 6"``) already negates feet and inches together.
    """

    imperial = staticmethod(position_parser._parse_imperial_elevation)
    metric = staticmethod(position_parser._parse_metric_elevation)

    def setUp(self):
        position_parser.clear_caches()
        self.addCleanup(position_parser.clear_caches)

    def test_a_detached_minus_negates_feet_and_inches_together(self):
        table = (
            ("- 5' 6\"", -66.0),
            ("-  5' 6\"", -66.0),
            ("- 5' 6 1/2\"", -66.5),
            ("- 5'-6\"", -66.0),
            ("- 5' - 6\"", -66.0),
            ("- 0' 6\"", -6.0),
            ('- 5′ 6"', -66.0),
            ("- 5'x", -60.0),
            ("- 4' 2\"", -50.0),
        )
        for text, expected in table:
            with self.subTest(text=text):
                self.assertEqual(self.imperial(text), expected)
                self.assertEqual(
                    self.imperial(text), self.imperial(text.replace("- ", "-", 1))
                )

    def test_attached_and_absent_signs_read_as_before(self):
        table = (
            ("5' 6\"", 66.0),
            ("-5' 6\"", -66.0),
            ("5'-6\"", 66.0),
            ("-5' -6\"", -66.0),
            ('- 6"', -6.0),
            ("-5'x", -60.0),
        )
        for text, expected in table:
            with self.subTest(text=text):
                self.assertEqual(self.imperial(text), expected)

    def test_a_detached_minus_in_metric_text_is_read_not_refused(self):
        table = (
            ("- 1m", -100.0),
            ("- 1 m", -100.0),
            ("- 1,5 m", -150.0),
            ("- 20cm", -20.0),
            ("- 3 meters", -300.0),
            ("- 1m 20cm", -120.0),
            ("1m - 20cm", 80.0),
            ("- 1m - 20cm", -120.0),
        )
        for text, expected in table:
            with self.subTest(text=text):
                self.assertEqual(self.metric(text), expected)
                self.assertEqual(
                    self.metric(text), self.metric(text.replace("- ", "-"))
                )

    def test_the_entry_points_agree_for_a_detached_minus(self):
        for name, expected in (
            ("Wall @T - 5' 6\"", (-66.0, True)),
            ("Wall @B - 5' 6\"", (-66.0, False)),
            ('Wall @T - 6"', (-6.0, True)),
            ("Wall @T - 1 m", (-100.0 / 2.54, True)),
            ("Wall @T - 20cm", (-20.0 / 2.54, True)),
        ):
            with self.subTest(name=name):
                self.assertEqual(extract_z_value_from_name(name), expected)
                self.assertEqual(
                    extract_z_value_from_name(name),
                    extract_z_value_from_name(name.replace("- ", "-", 1)),
                )
        self.assertEqual(
            convert_elevation_in_name("Wall @T - 5' 6\"", True), "Wall @T -167.64 cm"
        )
        self.assertEqual(
            convert_elevation_in_name("Wall @T - 5' 6\"", False), "Wall @T -5' 6\""
        )
        self.assertEqual(
            convert_elevation_in_name("Wall @T - 1 m", True), "Wall @T -100 cm"
        )
        self.assertEqual(
            convert_elevation_in_name("Wall @T - 1 m", False), "Wall @T -3' 3 3/8\""
        )


class MetricSignAppliesToTheWholeValueTests(unittest.TestCase):
    """A leading minus before the metres part negates metres plus centimetres."""

    metric = staticmethod(position_parser._parse_metric_elevation)

    def setUp(self):
        position_parser.clear_caches()
        self.addCleanup(position_parser.clear_caches)

    def test_a_leading_minus_negates_metres_and_centimetres_together(self):
        table = (
            ("-1m 20cm", -120.0),
            ("-1m and 20cm", -120.0),
            ("-1m+20cm", -120.0),
            ("-1.5m 20cm", -170.0),
            ("-1,5 m 20 cm", -170.0),
            ("-1m 2.5cm", -102.5),
            ("-0m 20cm", -20.0),
            ("- 1m 20cm", -120.0),
            ("x -1m 20cm", -120.0),
        )
        for text, expected in table:
            with self.subTest(text=text):
                self.assertEqual(self.metric(text), expected)

    def test_a_minus_on_the_centimetres_alone_still_subtracts(self):
        table = (
            ("1m -20cm", 80.0),
            ("1m and -20cm", 80.0),
            ("1m+-20cm", 80.0),
            ("1m - 20cm", 80.0),
            ("1m -2.5cm", 97.5),
        )
        for text, expected in table:
            with self.subTest(text=text):
                self.assertEqual(self.metric(text), expected)

    def test_both_parts_signed_stay_negative(self):
        for text in ("-1m -20cm", "- 1m - 20cm", "-1m and -20cm"):
            with self.subTest(text=text):
                self.assertEqual(self.metric(text), -120.0)

    def test_unsigned_and_single_unit_values_are_unchanged(self):
        table = (
            ("1m 20cm", 120.0),
            ("-1m", -100.0),
            ("-20cm", -20.0),
            ("-3 meters", -300.0),
            ("-30 centimeters", -30.0),
        )
        for text, expected in table:
            with self.subTest(text=text):
                self.assertEqual(self.metric(text), expected)

    def test_the_name_entry_points_apply_the_sign_to_the_whole_value(self):
        for name, centimetres in (
            ("Wall @T -1m 20cm", -120.0),
            ("Wall @B -1m 20cm", -120.0),
            ("Wall @T - 1m 20cm", -120.0),
            ("Wall @T -1m -20cm", -120.0),
            ("Wall @T 1m -20cm", 80.0),
        ):
            with self.subTest(name=name):
                value, is_top = extract_z_value_from_name(name)
                self.assertAlmostEqual(value, centimetres / 2.54, places=9)
                self.assertIs(is_top, "@T" in name)
        table = (
            ("Wall @T -1m 20cm", "Wall @T -120 cm", "Wall @T -3' 11 1/4\""),
            ("Wall @T - 1m 20cm", "Wall @T -120 cm", "Wall @T -3' 11 1/4\""),
            ("Wall @T -1m -20cm", "Wall @T -120 cm", "Wall @T -3' 11 1/4\""),
            ("Wall @T 1m -20cm", "Wall @T 80 cm", "Wall @T 2' 7 1/2\""),
        )
        for name, metric, imperial in table:
            with self.subTest(name=name):
                self.assertEqual(convert_elevation_in_name(name, True), metric)
                self.assertEqual(convert_elevation_in_name(name, False), imperial)

    def test_metric_and_imperial_signs_agree_for_the_same_length(self):
        self.assertEqual(
            extract_z_value_from_name("Wall @T -1m 20cm")[0],
            -extract_z_value_from_name("Wall @T 1m 20cm")[0],
        )
        self.assertEqual(
            position_parser._parse_imperial_elevation("-5' 6\""),
            -position_parser._parse_imperial_elevation("5' 6\""),
        )


class MetricFormattingDropsRoundingNoiseTests(unittest.TestCase):
    """A converted length that is a whole number of centimetres prints without decimals."""

    fmt = staticmethod(position_parser._format_metric_elevation)

    def setUp(self):
        position_parser.clear_caches()
        self.addCleanup(position_parser.clear_caches)

    def test_one_centimetre_converts_to_a_whole_number(self):
        self.assertEqual(convert_elevation_in_name("Wall @T 1cm", True), "Wall @T 1 cm")
        self.assertEqual(
            convert_elevation_in_name("Wall @B 1 cm", True), "Wall @B 1 cm"
        )

    def test_every_whole_centimetre_value_prints_without_decimals(self):
        for whole in range(-500, 501):
            with self.subTest(cm=whole):
                self.assertEqual(self.fmt(whole / 2.54), f"{whole} cm")
                self.assertEqual(
                    convert_elevation_in_name(f"Wall @T {whole}cm", True),
                    f"Wall @T {whole} cm",
                )

    def test_fractional_centimetres_keep_two_decimals(self):
        table = (
            (1.5, "1.50 cm"),
            (-1.5, "-1.50 cm"),
            (0.25, "0.25 cm"),
            (102.5, "102.50 cm"),
            (1.01, "1.01 cm"),
            (167.64, "167.64 cm"),
        )
        for cm, expected in table:
            with self.subTest(cm=cm):
                self.assertEqual(self.fmt(cm / 2.54), expected)

    def test_noise_below_a_hundredth_is_rounded_before_the_integer_check(self):
        table = (
            (1.004, "1 cm"),
            (0.996, "1 cm"),
            (-1.004, "-1 cm"),
            (1.006, "1.01 cm"),
            (1.494, "1.49 cm"),
            (1.496, "1.50 cm"),
            (0.004, "0 cm"),
            (-0.004, "0 cm"),
        )
        for cm, expected in table:
            with self.subTest(cm=cm):
                self.assertEqual(self.fmt(cm / 2.54), expected)

    def test_converting_to_metric_twice_gives_the_same_name(self):
        names = (
            "Wall @T 1cm",
            "Wall @T 1.5cm",
            "Wall @T 1m 20cm",
            "Wall @T -1m 20cm",
            'Wall @T 6"',
            "Wall @B 5' 6\"",
            'Wall @B 3 1/2"',
            "Wall @T 2.55 cm",
            "Wall @T 0.01 cm",
        )
        for name in names:
            with self.subTest(name=name):
                once = convert_elevation_in_name(name, True)
                self.assertEqual(convert_elevation_in_name(once, True), once)

    def test_every_two_decimal_centimetre_value_is_stable_under_repeated_conversion(
        self,
    ):
        for hundredths in range(0, 2001):
            text = f"Wall @T {hundredths / 100:.2f} cm"
            with self.subTest(text=text):
                once = convert_elevation_in_name(text, True)
                self.assertNotIn(".00 cm", once)
                self.assertEqual(convert_elevation_in_name(once, True), once)


class RegexInternalDigitRunAndSpacingTests(unittest.TestCase):
    """Two-digit runs, optional spaces and unit boundaries inside the elevation regexes.
    Every expected value is derived by hand from the grammar: feet are worth 12
    inches, a trailing fraction adds numerator/denominator inches, a metric value
    is centimetres (metres * 100) divided by 2.54 for the inch result.
    """

    def setUp(self):
        position_parser.clear_caches()
        self.addCleanup(position_parser.clear_caches)

    def test_feet_and_inches_with_two_digit_and_sixteenth_parts(self):
        table = (
            ("Wall @T 5' 10\"", 70.0),  # 5 * 12 + 10
            ("Wall @T 5' 11\"", 71.0),  # 5 * 12 + 11
            ("Wall @T 12' 3\"", 147.0),  # 12 * 12 + 3
            ("Wall @T 10' 10\"", 130.0),  # 10 * 12 + 10
            ("Wall @T 5' 6 11/16\"", 66.6875),  # 66 + 11/16
            ("Wall @T 5' 6 1/16\"", 66.0625),  # 66 + 1/16
            ("Wall @T 5' 6 15/16\"", 66.9375),  # 66 + 15/16
        )
        for name, inches in table:
            with self.subTest(name=name):
                self.assertEqual(extract_z_value_from_name(name), (inches, True))

    def test_a_space_before_the_prime_or_before_the_closing_quote_is_allowed(self):
        table = (
            ("Wall @T 5 ' 6\"", 66.0),
            ("Wall @T 5' 6 \"", 66.0),
            ("Wall @T 5 ' 6 \"", 66.0),
            ("Wall @T -5 ' 6\"", -66.0),
            ("Wall @T 5' 6 1/2 \"", 66.5),
        )
        for name, inches in table:
            with self.subTest(name=name):
                self.assertEqual(extract_z_value_from_name(name), (inches, True))

    def test_a_bare_fraction_directly_after_the_feet_mark_is_the_inches_part(self):
        """Characterisation of an incidental form, not a documented input format."""
        # "5'3/4"" cannot read "3" as whole inches (no closing quote follows it),
        # so the regex falls back to the fraction alternative: 60 + 3/4. (The
        # validity gate only admits this form glued to the prime, via "\b".)
        table = (
            ("Wall @T 5'3/4\"", 60.75),
            ("Wall @T 5'3/16\"", 60.1875),
            ("Wall @T 5'13/16\"", 60.8125),
            ("Wall @T -5'3/4\"", -60.75),
        )
        for name, inches in table:
            with self.subTest(name=name):
                self.assertEqual(extract_z_value_from_name(name), (inches, True))

    def test_feet_only_values_with_two_digits_or_a_space_before_the_prime(self):
        table = (
            ("Wall @T 20'x", 240.0),  # 20 * 12
            ("Wall @T 11 'x", 132.0),  # 11 * 12
            ("Wall @T 10'x", 120.0),
            ("Wall @T -12 'x", -144.0),
        )
        for name, inches in table:
            with self.subTest(name=name):
                self.assertEqual(extract_z_value_from_name(name), (inches, True))

    def test_inches_only_values_with_two_digits_a_space_or_a_sixteenth_fraction(self):
        table = (
            ('Wall @T 12"', 12.0),
            ('Wall @T 6 "', 6.0),
            ('Wall @T 11 1/2"', 11.5),  # 11 + 1/2
            ('Wall @T 1 7/16"', 1.4375),  # 1 + 7/16
            ('Wall @T 6 11/16"', 6.6875),  # 6 + 11/16
            ('Wall @T 11/16"', 0.6875),  # bare fraction, two-digit numerator
            ('Wall @T 5/16 "', 0.3125),  # bare fraction, space before the quote
            ('Wall @T -11 1/2"', -11.5),
        )
        for name, inches in table:
            with self.subTest(name=name):
                self.assertEqual(extract_z_value_from_name(name), (inches, True))

    def test_metric_values_with_two_digit_metres_or_centimetres_and_decimals(self):
        table = (
            ("Wall @T 11m 20cm", 1120.0),  # 11 * 100 + 20
            ("Wall @T 1m 25cm", 125.0),  # 1 * 100 + 25
            ("Wall @T 1.25m 20cm", 145.0),  # 1.25 * 100 + 20
            ("Wall @T 1m 2.50cm", 102.5),  # 100 + 2.5
            ("Wall @T 11 m", 1100.0),  # 11 * 100
            ("Wall @T 11.5 m", 1150.0),
            ("Wall @T 12 meters", 1200.0),
            ("Wall @T 25 cm", 25.0),
            ("Wall @T 12.5 cm", 12.5),
            ("Wall @T 12 centimeters", 12.0),
        )
        for name, centimetres in table:
            with self.subTest(name=name):
                value, is_top = extract_z_value_from_name(name)
                self.assertAlmostEqual(value, centimetres / 2.54, places=9)
                self.assertIs(is_top, True)

    def test_a_metric_unit_is_not_taken_from_the_start_of_a_longer_word(self):
        # "5 cm" is the whole reading; the trailing "2mm" must not be read as 2 m
        # (which would give 5 cm -> 2 m = 200 cm) because "m" needs a word boundary.
        value, is_top = extract_z_value_from_name("Wall @T 5 cm 2mm")
        self.assertAlmostEqual(value, 5 / 2.54, places=9)
        self.assertIs(is_top, True)

    def test_private_metric_helper_needs_a_word_boundary_after_each_unit(self):
        # Characterisation of the private helper (public paths gate on the
        # validity patterns first): a unit glued to more letters is not a unit.
        metric = position_parser._parse_metric_elevation
        self.assertEqual(metric("5cmx"), 0.0)
        self.assertEqual(metric("5mx"), 0.0)
        self.assertEqual(metric("5 cm 2mm"), 5.0)

    def test_conversion_to_metric_uses_the_same_digit_runs_and_spacing(self):
        table = (
            ("Wall @T 11m 20cm", "Wall @T 1120 cm"),
            ("Wall @T 1.25m 20cm", "Wall @T 145 cm"),
            ("Wall @T 11 m", "Wall @T 1100 cm"),
            ("Wall @T 25 cm", "Wall @T 25 cm"),
            ("Wall @T 5' 10\"", "Wall @T 177.80 cm"),  # 70 * 2.54
            ("Wall @T 5 ' 6 \"", "Wall @T 167.64 cm"),  # 66 * 2.54
            ('Wall @T 12"', "Wall @T 30.48 cm"),  # 12 * 2.54
            ("Wall @T 5' 6 11/16\"", "Wall @T 169.39 cm"),  # 66.6875 * 2.54
        )
        for name, expected in table:
            with self.subTest(name=name):
                self.assertEqual(convert_elevation_in_name(name, True), expected)


class ElevationValidityGateSpacingAndBoundaryTests(unittest.TestCase):
    """Spacing, decimals and word boundaries inside the validity patterns.
    The gate (prefix match for extraction, whole-text match for conversion) is
    separate from the value regexes, so each form is checked through the entry
    point that actually depends on it.
    """

    def setUp(self):
        position_parser.clear_caches()
        self.addCleanup(position_parser.clear_caches)

    def test_a_detached_minus_before_a_feet_only_value_is_accepted(self):
        # "- 5'x" is -5 feet = -60 inches: the gate allows spaces after the minus.
        self.assertEqual(extract_z_value_from_name("Wall @T - 5'x"), (-60.0, True))
        self.assertEqual(extract_z_value_from_name("Wall @B - 12 'x"), (-144.0, False))

    def test_inches_glued_to_a_fraction_are_not_a_readable_elevation(self):
        # After the prime "611/16" has no whitespace between a whole number and a
        # fraction, and no word boundary follows the prime, so no pattern admits it.
        name = "Wall @T 5' 611/16\""
        self.assertEqual(extract_z_value_from_name(name), (0.0, False))
        self.assertEqual(convert_elevation_in_name(name, True), name)

    def test_a_centimetre_unit_glued_to_more_letters_is_not_an_elevation(self):
        for name in ("Wall @T 5cmx", "Wall @T 5 centimetersx", "Wall @B 12 cmx"):
            with self.subTest(name=name):
                self.assertEqual(extract_z_value_from_name(name), (0.0, False))
                self.assertEqual(convert_elevation_in_name(name, True), name)

    def test_a_compound_metric_value_converts_with_any_of_its_optional_spaces(self):
        # metres*100 +/- centimetres, then shown as centimetres
        table = (
            ("Wall @T 1 m 20cm", "Wall @T 120 cm"),  # space before "m"
            ("Wall @T 1m 20 cm", "Wall @T 120 cm"),  # space before "cm"
            ("Wall @T 1m and -2cm", "Wall @T 98 cm"),  # 100 - 2, space after "and"
            ("Wall @T 1m + -2cm", "Wall @T 98 cm"),  # 100 - 2, space after "+"
            ("Wall @T 1m - 20cm", "Wall @T 80 cm"),  # 100 - 20, detached minus
            ("Wall @T 1m 2.5cm", "Wall @T 102.50 cm"),  # 100 + 2.5
            ("Wall @T 1m 2.50cm", "Wall @T 102.50 cm"),  # 100 + 2.50
            ("Wall @T 1,5 m 2,5 cm", "Wall @T 152.50 cm"),  # 150 + 2.5
        )
        for name, expected in table:
            with self.subTest(name=name):
                self.assertEqual(convert_elevation_in_name(name, True), expected)


class RunsOfWhitespaceAndDecimalPointTests(unittest.TestCase):
    """Every optional space accepts a run of spaces; a decimal point needs digits.
    Expected values are derived from the grammar: feet are worth 12 inches, a
    metric value is metres * 100 plus centimetres (a leading minus negates the
    whole value), divided by 2.54 for the inch result.
    """

    def setUp(self):
        position_parser.clear_caches()
        self.addCleanup(position_parser.clear_caches)

    def test_imperial_values_accept_runs_of_spaces_around_every_mark(self):
        table = (
            ("Wall @T 5  ' 6\"", 66.0),  # two spaces before the prime
            ("Wall @T 5' 6  \"", 66.0),  # two spaces before the closing quote
            ("Wall @T 5   '   6   \"", 66.0),  # runs of three
            ("Wall @T 5'  -  6\"", 66.0),  # the dash is only a separator
            ("Wall @T 5' -  6\"", 66.0),
            ("Wall @T -  5'x", -60.0),  # two spaces after the minus (feet only)
            ("Wall @T 5  'x", 60.0),  # two spaces before the prime (feet only)
            ('Wall @T -  6"', -6.0),  # two spaces after the minus (inches only)
            ('Wall @T 6  "', 6.0),  # two spaces before the quote (inches only)
            ('Wall @T 1/2  "', 0.5),
            ('Wall @T 11  1/2  "', 11.5),
        )
        for name, inches in table:
            with self.subTest(name=name):
                self.assertEqual(extract_z_value_from_name(name), (inches, True))

    def test_metric_values_accept_runs_of_spaces_around_every_mark(self):
        table = (
            ("Wall @T -  1m 20cm", -120.0),  # -(100 + 20)
            ("Wall @T 1  m 20  cm", 120.0),
            ("Wall @T 1m  and  20cm", 120.0),
            ("Wall @T 1m  +  20cm", 120.0),
            ("Wall @T -  1 m", -100.0),
            ("Wall @T 1  m", 100.0),
            ("Wall @T -  20 cm", -20.0),
            ("Wall @T 20  cm", 20.0),
            ("Wall @T 1   m   20   cm", 120.0),
            ("Wall @T 1m and  -  20cm", 80.0),  # 100 + (-20), runs after and / minus
            ("Wall @T 1m -  20cm", 80.0),
        )
        for name, centimetres in table:
            with self.subTest(name=name):
                value, is_top = extract_z_value_from_name(name)
                self.assertAlmostEqual(value, centimetres / 2.54, places=9)
                self.assertIs(is_top, True)

    def test_a_decimal_point_without_digits_is_not_part_of_the_number(self):
        # "2." is not a decimal number, so the compound "1m 2.cm" is not read and the
        # value falls back to the leading "1m" (100 cm); likewise "2.m" is no metre
        # reading, so "5 cm" stands (the gate admits the leading, readable unit).
        table = (
            ("Wall @T 1m 2.cm", 100.0),
            ("Wall @T 1m 2x3cm", 100.0),  # "2x3cm" is not a number plus cm
            ("Wall @T 5 cm 2.m", 5.0),
        )
        for name, centimetres in table:
            with self.subTest(name=name):
                value, is_top = extract_z_value_from_name(name)
                self.assertAlmostEqual(value, centimetres / 2.54, places=9)
                self.assertIs(is_top, True)

    def test_private_metric_helper_search_does_not_bridge_a_broken_number(self):
        # Characterisation of the private helper's unanchored search (the public
        # gate rejects most of these): the number must be digits, an optional
        # '.digits', and then the unit, so noise before it is skipped, not parsed.
        metric = position_parser._parse_metric_elevation
        self.assertEqual(metric("2x5m"), 500.0)  # finds "5m"
        self.assertEqual(metric("2x5cm"), 5.0)  # finds "5cm"
        self.assertEqual(metric("1x2m 3cm"), 203.0)  # finds "2m 3cm"
        self.assertEqual(metric("1.m 2cm"), 2.0)  # "1." is not a number
        self.assertEqual(metric("2.m"), 0.0)
        self.assertEqual(metric("2.cm"), 0.0)
        self.assertEqual(metric("1m 2.cm"), 100.0)


if __name__ == "__main__":
    unittest.main()
