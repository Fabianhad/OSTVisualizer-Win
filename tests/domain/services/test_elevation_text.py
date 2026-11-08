import unittest
from ost_visualizer.domain.services.elevation_text import (
    ELEVATION_TEXT_PATTERNS,
    is_elevation_text,
    is_strippable_elevation_text,
)


class ElevationTextTests(unittest.TestCase):
    def test_the_six_published_patterns_drive_the_validity_check(self):
        self.assertEqual(len(ELEVATION_TEXT_PATTERNS), 6)
        for text in ("745' 0\"", '6"', "1m 20cm", "2 m", "30 cm", "5'x"):
            with self.subTest(text=text):
                self.assertTrue(is_elevation_text(text))

    def test_feet_alone_is_not_valid_for_derivation_but_is_strippable(self):
        for text in ("5'", "-4'", "5′", "5' "):
            with self.subTest(text=text):
                self.assertFalse(is_elevation_text(text))
                self.assertTrue(is_strippable_elevation_text(text))

    def test_everything_valid_is_strippable(self):
        for text in ("745' 0\"", "12' 6 1/2\"", "1m+20cm"):
            with self.subTest(text=text):
                self.assertTrue(is_strippable_elevation_text(text))

    def test_text_that_is_not_an_elevation_is_neither(self):
        for text in ("", "later", "5pm", "5' wall", "@T 5'", "m"):
            with self.subTest(text=text):
                self.assertFalse(is_elevation_text(text))
                self.assertFalse(is_strippable_elevation_text(text))


class ElevationTextPatternTests(unittest.TestCase):
    """Each published pattern is also used on its own (full-text check in the position parser)."""

    # pattern -> ((text, exactly the prefix the pattern matches), ...)
    ACCEPTED = (
        (
            "IMPERIAL_FEET_INCHES",
            (
                ("745' 0\"", "745' 0\""),
                ("12' 6 1/2\"", "12' 6 1/2\""),
                ("12' 3  1/2\"", "12' 3  1/2\""),
                ("12'-6\"", "12'-6\""),
                ("5'- 6\"", "5'- 6\""),
                ("5'6\"", "5'6\""),
                ("5 ' 6 \"", "5 ' 6 \""),
                ("-  5' 6\"", "-  5' 6\""),
                ("- 5' 6\"", "- 5' 6\""),
                ('5′ 6"', '5′ 6"'),
                ("5'  -  6\"", "5'  -  6\""),
                ("5' 6\" and more", "5' 6\""),
            ),
        ),
        (
            "IMPERIAL_FEET_ONLY",
            (
                ("5'x", "5'"),
                ("5'6", "5'"),
                ("12'a", "12'"),
                ("- 5'x", "- 5'"),
                ("-  5'x", "-  5'"),
                ("5 'x", "5 '"),
                ("5′x", "5′"),
            ),
        ),
        (
            "IMPERIAL_INCHES_ONLY",
            (
                ('6"', '6"'),
                ('-6"', '-6"'),
                ('- 6"', '- 6"'),
                ('-  6"', '-  6"'),
                ('6 "', '6 "'),
                ('1/2"', '1/2"'),
                ('12/32"', '12/32"'),
                ('3 1/2"', '3 1/2"'),
                ('3  1/2"', '3  1/2"'),
                ('12 11/32"', '12 11/32"'),
                ('6" tall', '6"'),
            ),
        ),
        (
            "METRIC_M_PLUS_CM",
            (
                ("1m 20cm", "1m 20cm"),
                ("1m and 20cm", "1m and 20cm"),
                ("1m+20cm", "1m+20cm"),
                ("1m20cm", "1m20cm"),
                ("1mand20cm", "1mand20cm"),
                ("1m  and 20cm", "1m  and 20cm"),
                ("1m  + 20cm", "1m  + 20cm"),
                ("1m and  -20cm", "1m and  -20cm"),
                ("1m -  20cm", "1m -  20cm"),
                ("1m - 20cm", "1m - 20cm"),
                ("1m -20cm", "1m -20cm"),
                ("1  m 20cm", "1  m 20cm"),
                ("1m 20  cm", "1m 20  cm"),
                ("-  1m 20cm", "-  1m 20cm"),
                ("- 1m 20cm", "- 1m 20cm"),
                ("-1m20cm", "-1m20cm"),
                ("1,5m 20,5cm", "1,5m 20,5cm"),
                ("1.5m 20.5cm", "1.5m 20.5cm"),
                ("1M 20CM", "1M 20CM"),
                ("1 M AND 20 CM", "1 M AND 20 CM"),
                ("1m 20cm extra", "1m 20cm"),
            ),
        ),
        (
            "METRIC_METERS_ONLY",
            (
                ("2 m", "2 m"),
                ("2m", "2m"),
                ("2  m", "2  m"),
                ("2.5m", "2.5m"),
                ("2,5 m", "2,5 m"),
                ("2 meter", "2 meter"),
                ("2 meters", "2 meters"),
                ("2METERS", "2METERS"),
                ("-2m", "-2m"),
                ("- 2m", "- 2m"),
                ("-  2m", "-  2m"),
                ("2m+3", "2m"),
                ("2 m 30cm", "2 m"),
            ),
        ),
        (
            "METRIC_CM_ONLY",
            (
                ("30 cm", "30 cm"),
                ("30cm", "30cm"),
                ("30  cm", "30  cm"),
                ("30.5cm", "30.5cm"),
                ("30,5 cm", "30,5 cm"),
                ("30,5cm", "30,5cm"),
                ("30 centimeter", "30 centimeter"),
                ("30 centimeters", "30 centimeters"),
                ("30CENTIMETERS", "30CENTIMETERS"),
                ("-30cm", "-30cm"),
                ("- 30 cm", "- 30 cm"),
                ("-  30cm", "-  30cm"),
                ("30cm x", "30cm"),
            ),
        ),
    )
    REJECTED = (
        (
            "IMPERIAL_FEET_INCHES",
            (
                "",
                "'5\"",
                '5"',
                "5'",
                "5' 6",
                "--5' 6\"",
                "5'--6\"",
                "5'- -6\"",
                "5's6\"",
                "5' 6 /2\"",
                "5' 6 1/\"",
                "5' 6 1/2 1/2\"",
                "5' 6 x\"",
            ),
        ),
        (
            "IMPERIAL_FEET_ONLY",
            ("", "'", "'5", "'m", "--5'x", "5'", "5' ", "5' x", "5''", "x5'x"),
        ),
        (
            "IMPERIAL_INCHES_ONLY",
            (
                "",
                '"',
                '-"',
                '/5"',
                '5/"',
                '--5"',
                '3 /4"',
                '3 4/"',
                '1 1/2 1/2"',
                "6",
                'x6"',
            ),
        ),
        (
            "METRIC_M_PLUS_CM",
            (
                "",
                "1m",
                "5cm",
                "m5cm",
                "M5CM",
                "5mcm",
                "1m cm",
                "5.m 2cm",
                "5,m2cm",
                "5m 1.cm",
                "12m12.cm",
                "--5m 20cm",
                "1m --20cm",
                "1.2.3m 5cm",
                "1m 2.3.4cm",
                "1m and+ 20cm",
                "1mand and20cm",
            ),
        ),
        (
            "METRIC_METERS_ONLY",
            (
                "",
                "m",
                "--2m",
                "5.m",
                "5,m",
                ".5m",
                "1.2.3m",
                "5meterss",
                "5mx",
                "5mm",
                "5 meterx",
            ),
        ),
        (
            "METRIC_CM_ONLY",
            (
                "",
                "cm",
                "--5cm",
                "5.cm",
                "5,cm",
                "1.2.3cm",
                "5centimeterss",
                "5cmx",
                "5 centimete",
            ),
        ),
    )

    def test_every_pattern_has_a_table_and_the_published_tuple_keeps_its_order(self):
        from ost_visualizer.domain.services import elevation_text

        names = [name for name, _ in self.ACCEPTED]
        self.assertEqual(names, [name for name, _ in self.REJECTED])
        self.assertEqual(
            tuple(getattr(elevation_text, name) for name in names),
            ELEVATION_TEXT_PATTERNS,
        )

    def test_each_pattern_matches_exactly_the_documented_prefix(self):
        from ost_visualizer.domain.services import elevation_text

        for name, cases in self.ACCEPTED:
            pattern = getattr(elevation_text, name)
            self.assertGreaterEqual(len(cases), 7)
            for text, prefix in cases:
                with self.subTest(pattern=name, text=text):
                    found = pattern.match(text)
                    self.assertIsNotNone(found)
                    self.assertEqual(found.group(0), prefix)
                    self.assertTrue(is_elevation_text(text))
                    self.assertTrue(is_strippable_elevation_text(text))

    def test_each_pattern_refuses_malformed_text(self):
        from ost_visualizer.domain.services import elevation_text

        for name, cases in self.REJECTED:
            pattern = getattr(elevation_text, name)
            self.assertGreaterEqual(len(cases), 6)
            for text in cases:
                with self.subTest(pattern=name, text=text):
                    self.assertIsNone(pattern.match(text))

    def test_text_that_no_pattern_matches_is_neither_elevation_nor_strippable(self):
        for text in (
            "",
            " ",
            "m",
            "cm",
            "-",
            "/",
            "'5\"",
            '"',
            '-"',
            '/5"',
            '5/"',
            "'5",
            "'m",
            "m5cm",
            "5mcm",
            "5.m",
            "5.cm",
            "--5'x",
            "--5' 6\"",
            '--5"',
            "--5m",
            "--5cm",
            "5'--6\"",
            "1.2.3m",
            "1.2.3cm",
            "5meterss",
            "5centimeterss",
            "5mx",
            "5cmx",
        ):
            with self.subTest(text=text):
                self.assertFalse(is_elevation_text(text))
                self.assertFalse(is_strippable_elevation_text(text))

    def test_feet_alone_may_carry_a_minus_spaces_and_any_number_of_digits(self):
        for text in (
            "5'",
            "12'",
            "745'",
            "-5'",
            "- 5'",
            "-  5'",
            "  5'",
            "\t5'",
            "5 '",
            "5   '",
            "5'  ",
            "5'\t",
            "- 12 '  ",
            "5′",
            "12′",
            "- 5′",
            "5 ′",
        ):
            with self.subTest(text=text):
                self.assertFalse(is_elevation_text(text))
                self.assertTrue(is_strippable_elevation_text(text))

    def test_feet_alone_still_needs_digits_a_single_minus_and_nothing_after(self):
        for text in (
            "'",
            "′",
            " '",
            "-'",
            "--5'",
            "- -5'",
            "5''",
            "5' x",
            "5' 6",
            "5'.",
            "a5'",
            "5 ft",
        ):
            with self.subTest(text=text):
                self.assertFalse(is_strippable_elevation_text(text))


class ElevationTextSeparatorTests(unittest.TestCase):
    """Every separator slot is a whitespace class (tab, NBSP and newline included), not a plain space."""

    # (pattern, text, exactly the prefix the pattern matches)
    WHITESPACE = (
        ("IMPERIAL_FEET_INCHES", "\t5'5\"", "\t5'5\""),
        ("IMPERIAL_FEET_INCHES", "\n5'5\"", "\n5'5\""),
        ("IMPERIAL_FEET_INCHES", "5\t'5\"", "5\t'5\""),
        ("IMPERIAL_FEET_INCHES", "5 '5\"", "5 '5\""),
        ("IMPERIAL_FEET_INCHES", "5'\t-5\"", "5'\t-5\""),
        ("IMPERIAL_FEET_INCHES", "5' 5\"", "5' 5\""),
        ("IMPERIAL_FEET_INCHES", "5'\n5\"", "5'\n5\""),
        ("IMPERIAL_FEET_INCHES", "5' 5\t1/2\"", "5' 5\t1/2\""),
        ("IMPERIAL_FEET_INCHES", "5'5\t\"", "5'5\t\""),
        ("IMPERIAL_FEET_INCHES", "5'5 \"", "5'5 \""),
        ("IMPERIAL_FEET_INCHES", "5' 5 1/2\t\"", "5' 5 1/2\t\""),
        ("IMPERIAL_FEET_ONLY", "\t5'x", "\t5'"),
        ("IMPERIAL_FEET_ONLY", "\n5'x", "\n5'"),
        ("IMPERIAL_FEET_ONLY", "5\t'x", "5\t'"),
        ("IMPERIAL_FEET_ONLY", "5 'x", "5 '"),
        ("IMPERIAL_FEET_ONLY", "\n12′1/2", "\n12′"),
        ("IMPERIAL_INCHES_ONLY", '\t5"', '\t5"'),
        ("IMPERIAL_INCHES_ONLY", ' 5"', ' 5"'),
        ("IMPERIAL_INCHES_ONLY", '5\t"', '5\t"'),
        ("IMPERIAL_INCHES_ONLY", '5\n"', '5\n"'),
        ("IMPERIAL_INCHES_ONLY", '5\t1/2"', '5\t1/2"'),
        ("METRIC_M_PLUS_CM", "\t5m5cm", "\t5m5cm"),
        ("METRIC_M_PLUS_CM", "5\tm5cm", "5\tm5cm"),
        ("METRIC_M_PLUS_CM", "5 m5cm", "5 m5cm"),
        ("METRIC_M_PLUS_CM", "5m\tand5cm", "5m\tand5cm"),
        ("METRIC_M_PLUS_CM", "5mand\t-5cm", "5mand\t-5cm"),
        ("METRIC_M_PLUS_CM", "5m-\t5cm", "5m-\t5cm"),
        ("METRIC_M_PLUS_CM", "5m5\tcm", "5m5\tcm"),
        ("METRIC_M_PLUS_CM", "5m5 cm", "5m5 cm"),
        ("METRIC_METERS_ONLY", "\t05meter", "\t05meter"),
        ("METRIC_METERS_ONLY", "5\tm", "5\tm"),
        ("METRIC_METERS_ONLY", "5  meters", "5  meters"),
        ("METRIC_METERS_ONLY", "5  meters", "5  meters"),
        ("METRIC_CM_ONLY", "\n\t0CM", "\n\t0CM"),
        ("METRIC_CM_ONLY", "5\tcm", "5\tcm"),
        ("METRIC_CM_ONLY", "0 \t  centimeter", "0 \t  centimeter"),
    )
    # one stray character in each separator or class slot: refused by every pattern
    STRAY = (
        '0x12"',
        '5x6"',
        '5x"',
        "5.'5\"",
        "5''5\"",
        '5//"',
        '5/x"',
        '5.5."',
        "5x",
        "11x",
        "550x",
        "5x5m",
        "5x5meters",
        "5x5cm",
        "5x1CM",
        "1m5x5cm",
        "0m0x5CM",
        "5x1m 2cm",
    )

    def test_whitespace_of_any_kind_separates_the_parts(self):
        from ost_visualizer.domain.services import elevation_text

        self.assertGreaterEqual(len(self.WHITESPACE), 30)
        for name, text, prefix in self.WHITESPACE:
            with self.subTest(pattern=name, text=text):
                found = getattr(elevation_text, name).match(text)
                self.assertIsNotNone(found)
                self.assertEqual(found.group(0), prefix)
                self.assertIs(is_elevation_text(text), True)
                self.assertIs(is_strippable_elevation_text(text), True)

    def test_a_foreign_character_in_a_separator_slot_is_refused_everywhere(self):
        for text in self.STRAY:
            for pattern in ELEVATION_TEXT_PATTERNS:
                with self.subTest(text=text, pattern=pattern.pattern[:24]):
                    self.assertIsNone(pattern.match(text))
            with self.subTest(text=text):
                self.assertIs(is_elevation_text(text), False)
                self.assertIs(is_strippable_elevation_text(text), False)
        self.assertEqual(len(ELEVATION_TEXT_PATTERNS), 6)

    def test_feet_alone_accepts_every_kind_of_whitespace(self):
        for text in ("0\t'  ", "5\t'", "5' ", "\n5'", " 5'", "5\n′\t"):
            with self.subTest(text=text):
                self.assertIs(is_elevation_text(text), False)
                self.assertIs(is_strippable_elevation_text(text), True)

    def test_the_checks_return_real_booleans(self):
        for text, elevation, strippable in (
            ("5m", True, True),
            ("5' 6\"", True, True),
            ("5'", False, True),
            ("-5'", False, True),
            ("5′", False, True),
            ("later", False, False),
            ("", False, False),
            ("5x", False, False),
        ):
            with self.subTest(text=text):
                self.assertIs(is_elevation_text(text), elevation)
                self.assertIs(is_strippable_elevation_text(text), strippable)


class ElevationTextQuantifierTests(unittest.TestCase):
    """Repeat counts: any number of spaces, any number of digits, and a digit run in every number slot."""

    ACCEPTED = (
        # several spaces before the foot mark and before the closing quote
        ("IMPERIAL_FEET_INCHES", "5  '5\"", "5  '5\""),
        ("IMPERIAL_FEET_INCHES", "5     '5\"", "5     '5\""),
        ("IMPERIAL_FEET_INCHES", "5' 6  \"", "5' 6  \""),
        ("IMPERIAL_FEET_INCHES", "5' 6     \"", "5' 6     \""),
        ("IMPERIAL_FEET_ONLY", "5  'x", "5  '"),
        ("IMPERIAL_FEET_ONLY", "5     'x", "5     '"),
        ("IMPERIAL_INCHES_ONLY", '5  "', '5  "'),
        ("IMPERIAL_INCHES_ONLY", '5     "', '5     "'),
        # more than one digit in the inches, the numerator and the denominator
        ("IMPERIAL_FEET_INCHES", "5' 12\"", "5' 12\""),
        ("IMPERIAL_FEET_INCHES", "5' 123\"", "5' 123\""),
        ("IMPERIAL_FEET_INCHES", "5' 6 12/2\"", "5' 6 12/2\""),
        ("IMPERIAL_FEET_INCHES", "5' 6 1/12\"", "5' 6 1/12\""),
        ("IMPERIAL_FEET_INCHES", "5' 6 123/456\"", "5' 6 123/456\""),
        # more than one digit in the metres, and in every decimal part
        ("METRIC_M_PLUS_CM", "12m5cm", "12m5cm"),
        ("METRIC_M_PLUS_CM", "123m5cm", "123m5cm"),
        ("METRIC_M_PLUS_CM", "5.12m5cm", "5.12m5cm"),
        ("METRIC_M_PLUS_CM", "5,123m5cm", "5,123m5cm"),
        ("METRIC_M_PLUS_CM", "5m5.12cm", "5m5.12cm"),
        ("METRIC_M_PLUS_CM", "5m5,123cm", "5m5,123cm"),
        ("METRIC_METERS_ONLY", "5.12m", "5.12m"),
        ("METRIC_METERS_ONLY", "5,123 meters", "5,123 meters"),
        ("METRIC_CM_ONLY", "5.12cm", "5.12cm"),
        ("METRIC_CM_ONLY", "5,123 centimeters", "5,123 centimeters"),
    )
    REJECTED = (
        # the inches need at least one digit, and a fraction needs a space before it
        ("IMPERIAL_FEET_INCHES", "5' \""),
        ("IMPERIAL_FEET_INCHES", "5'\""),
        ("IMPERIAL_FEET_INCHES", "5' 61/2\""),
        ("IMPERIAL_FEET_INCHES", "5' 6 12/\""),
        ("IMPERIAL_FEET_INCHES", "5' 6 /12\""),
        ("IMPERIAL_INCHES_ONLY", '61/2 1/2"'),
    )

    def test_repeat_counts_are_open_ended_where_the_grammar_says_so(self):
        from ost_visualizer.domain.services import elevation_text

        for name, text, prefix in self.ACCEPTED:
            with self.subTest(pattern=name, text=text):
                found = getattr(elevation_text, name).match(text)
                self.assertIsNotNone(found)
                self.assertEqual(found.group(0), prefix)
                self.assertIs(is_elevation_text(text), True)
                self.assertIs(is_strippable_elevation_text(text), True)

    def test_a_missing_digit_run_or_fraction_separator_is_refused(self):
        from ost_visualizer.domain.services import elevation_text

        for name, text in self.REJECTED:
            with self.subTest(pattern=name, text=text):
                self.assertIsNone(getattr(elevation_text, name).match(text))


if __name__ == "__main__":
    unittest.main()
