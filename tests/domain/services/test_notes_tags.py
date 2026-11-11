import unittest
from ost_visualizer.domain.services.notes_tags import (
    FEET_PER_METRE,
    KeySpec,
    Length,
    ParsedTag,
    PercentOrLength,
    SectionsOrLength,
    TagFraction,
    TagLength,
    TagSchema,
    parse_length_ft,
    parse_notes_tags,
)

# A second, made-up object: adding one needs only a schema like this.
GATE = TagSchema(
    "gate",
    (
        KeySpec("leaves", SectionsOrLength(5.0, "leaves"), "2", 1, 4, "1 to 4 leaves"),
        KeySpec("swing", PercentOrLength(), "50%"),
        KeySpec("height", Length(), "6 ft", 2.0, 20.0, "2 ft to 20 ft"),
    ),
)
POST = TagSchema("post", (KeySpec("height", Length(), "3 ft"),))


def _parse(notes, schemas=(GATE, POST)):
    return parse_notes_tags(notes, schemas)


def _codes(warnings):
    return [(warning.code, warning.key) for warning in warnings]


class ParseLengthTests(unittest.TestCase):
    def test_a_number_with_no_unit_is_feet(self):
        for text, feet in (("40", 40.0), ("12.4", 12.4), (".5", 0.5), ("0", 0.0)):
            with self.subTest(text=text):
                self.assertEqual(parse_length_ft(text), feet)

    def test_the_ft_suffix_is_feet(self):
        for text, feet in (("40ft", 40.0), ("12.4ft", 12.4), ("40FT", 40.0)):
            with self.subTest(text=text):
                self.assertEqual(parse_length_ft(text), feet)
                self.assertEqual(parse_length_ft(text, bare_is_feet=False), feet)

    def test_the_m_suffix_is_metres_converted_to_feet(self):
        self.assertEqual(FEET_PER_METRE, 1 / 0.3048)
        for text, metres in (("10m", 10.0), ("3.77m", 3.77), (".5M", 0.5)):
            with self.subTest(text=text):
                self.assertAlmostEqual(parse_length_ft(text), metres / 0.3048, places=9)
        self.assertAlmostEqual(parse_length_ft("3.048m"), 10.0, places=9)

    def test_a_bare_number_can_be_refused_where_it_means_something_else(self):
        self.assertIsNone(parse_length_ft("40", bare_is_feet=False))
        self.assertEqual(parse_length_ft("40ft", bare_is_feet=False), 40.0)

    def test_other_units_and_malformed_numbers_are_rejected(self):
        for text in (
            "",
            " ",
            "ft",
            "m",
            "40in",
            "40cm",
            "40mm",
            "40yd",
            "40'",
            '6"',
            "40'6\"",
            "-40",
            "-40ft",
            "+40ft",
            "1e3",
            "1e3m",
            "nan",
            "inf",
            "4 0ft",
            "40ft6",
            "40ftm",
            "forty",
        ):
            with self.subTest(text=text):
                self.assertIsNone(parse_length_ft(text))


class TagGrammarTests(unittest.TestCase):
    def test_a_bare_tag_is_present_with_no_values(self):
        for notes in ("[gate]", "[GATE]", "[ Gate ]", "north side [gate] by others"):
            with self.subTest(notes=notes):
                parsed = _parse(notes)
                self.assertEqual(parsed.tag("gate"), ParsedTag(True, {}, ()))
                self.assertEqual(parsed.warnings, ())

    def test_arguments_take_spaces_commas_newlines_and_any_order_or_case(self):
        expected = {"leaves": 3, "swing": TagFraction(0.25), "height": TagLength(8.5)}
        for notes in (
            "[gate leaves=3 swing=25% height=8.5ft]",
            "[gate height=8.5, swing=25%, leaves=3]",
            "[gate,leaves=3,,swing=25% ,height=8.5ft]",
            "[GATE Leaves = 3\n  SWING= 25 %\n  Height =8.5 FT]",
        ):
            with self.subTest(notes=notes):
                tag = _parse(notes).tag("gate")
                self.assertEqual(tag.values, expected)
                self.assertEqual(tag.warnings, ())

    def test_a_length_key_reads_no_unit_ft_and_m(self):
        for text, feet in (
            ("10", 10.0),
            ("10ft", 10.0),
            ("10 ft", 10.0),
            ("3.048m", 10.0),
            ("3.048 m", 10.0),
        ):
            with self.subTest(text=text):
                tag = _parse(f"[gate height={text}]").tag("gate")
                self.assertEqual(set(tag.values), {"height"})
                self.assertAlmostEqual(tag.values["height"].feet, feet, places=9)
                self.assertEqual(tag.warnings, ())

    def test_sections_keys_take_a_count_or_a_length_with_a_unit(self):
        for text, leaves in (
            ("1", 1),
            ("4", 4),
            ("10ft", 2),
            ("14ft", 3),
            ("3.048m", 2),
            ("6m", 4),
        ):
            with self.subTest(text=text):
                tag = _parse(f"[gate leaves={text}]").tag("gate")
                self.assertEqual(tag.values, {"leaves": leaves})
                self.assertEqual(tag.warnings, ())

    def test_sections_given_as_a_length_note_the_rounded_result(self):
        tag = _parse("[gate leaves=14ft height=8]").tag("gate")
        self.assertEqual(tag.values["leaves"], 3)
        self.assertEqual(tag.notes, ("[gate]: leaves=14ft \u2192 3 leaves (15.0 ft).",))
        self.assertEqual(tag.warnings, ())
        metres = _parse("[gate leaves=3.048m]").tag("gate")
        self.assertEqual(
            metres.notes, ("[gate]: leaves=3.048m \u2192 2 leaves (10.0 ft).",)
        )
        # A count, a plain length key and a rejected length say nothing.
        for notes in ("[gate leaves=3]", "[gate height=8ft]", "[gate leaves=90ft]"):
            with self.subTest(notes=notes):
                self.assertEqual(_parse(notes).tag("gate").notes, ())

    def test_percent_keys_take_a_percentage_or_a_distance_in_feet(self):
        for text, value in (
            ("0%", TagFraction(0.0)),
            ("79%", TagFraction(0.79)),
            ("79 %", TagFraction(0.79)),
            ("12.5%", TagFraction(0.125)),
            ("100%", TagFraction(1.0)),
            ("150%", TagFraction(1.5)),
            ("0", TagLength(0.0)),
            ("0.7", TagLength(0.7)),
            ("1", TagLength(1.0)),
            ("30", TagLength(30.0)),
            ("30ft", TagLength(30.0)),
        ):
            with self.subTest(text=text):
                tag = _parse(f"[gate swing={text}]").tag("gate")
                self.assertEqual(tag.values, {"swing": value})
                self.assertEqual(tag.warnings, ())
        metres = _parse("[gate swing=3.048m]").tag("gate").values["swing"]
        self.assertAlmostEqual(metres.feet, 10.0, places=9)

    def test_absent_tags_and_ordinary_brackets_are_not_tags(self):
        for notes in ("", None, "gate", "(GATE)", "[see detail 5]", "[]", "[ ]", "[5]"):
            with self.subTest(notes=notes):
                parsed = _parse(notes)
                self.assertEqual(parsed.tag("gate"), ParsedTag())
                self.assertFalse(parsed.tag("gate").present)
                self.assertEqual(parsed.warnings, ())

    def test_two_different_objects_parse_independently(self):
        parsed = _parse("[gate leaves=3] and [post height=3ft]")
        self.assertEqual(parsed.tag("gate").values, {"leaves": 3})
        self.assertEqual(parsed.tag("post").values, {"height": TagLength(3.0)})
        self.assertEqual(parsed.warnings, ())


class TagWarningTests(unittest.TestCase):
    def test_bad_values_fall_back_and_name_the_default(self):
        cases = (
            "leaves=two",
            "leaves=2.5",
            "leaves=-1",
            "leaves=1e1",
            "leaves=nan",
            "leaves=",
            "leaves",
            "height=tall",
            "height=6in",
            "height=6'",
            "swing=half",
            "swing=-0.5",
            "swing=-5%",
            "swing=%",
            "swing=5%ft",
        )
        for argument in cases:
            with self.subTest(argument=argument):
                tag = _parse(f"[gate {argument}]").tag("gate")
                self.assertTrue(tag.present)
                self.assertEqual(tag.values, {})
                key = argument.partition("=")[0]
                self.assertEqual(_codes(tag.warnings), [("bad_value", key)])
                self.assertIn(argument, tag.warnings[0].message)
                self.assertIn("using", tag.warnings[0].message)

    def test_warnings_describe_lengths_in_feet(self):
        message = _parse("[gate height=tall]").tag("gate").warnings[0].message
        self.assertIn("a length in feet", message)
        self.assertIn("ft or m", message)
        self.assertIn("using 6 ft", message)
        message = _parse("[gate height=30]").tag("gate").warnings[0].message
        self.assertIn("outside 2 ft to 20 ft", message)

    def test_out_of_range_values_fall_back(self):
        for argument, key in (
            ("leaves=0", "leaves"),
            ("leaves=5", "leaves"),
            ("leaves=30m", "leaves"),
            ("height=1", "height"),
            ("height=1ft", "height"),
            ("height=7m", "height"),
            ("height=21", "height"),
        ):
            with self.subTest(argument=argument):
                tag = _parse(f"[gate {argument}]").tag("gate")
                self.assertEqual(tag.values, {})
                self.assertEqual(_codes(tag.warnings), [("out_of_range", key)])
        # A distance on a fraction key has no range of its own.
        self.assertEqual(_parse("[gate swing=99m]").tag("gate").warnings, ())

    def test_unknown_keys_flags_and_stray_text_are_reported_and_skipped(self):
        tag = _parse('[gate colour=red locked 7 name="a b" leaves=3]').tag("gate")
        self.assertEqual(tag.values, {"leaves": 3})
        self.assertEqual(
            _codes(tag.warnings),
            [
                ("unknown_key", "colour"),
                ("unknown_key", "locked"),
                ("unexpected_text", ""),
                ("unknown_key", "name"),
            ],
        )
        self.assertIn("leaves, swing, height", tag.warnings[0].message)

    def test_a_decimal_comma_is_a_separator(self):
        tag = _parse("[gate height=6,5]").tag("gate")
        self.assertEqual(tag.values, {"height": TagLength(6.0)})
        self.assertEqual(_codes(tag.warnings), [("unexpected_text", "")])

    def test_the_first_of_a_repeated_key_or_tag_wins(self):
        tag = _parse("[gate leaves=3 LEAVES=4]").tag("gate")
        self.assertEqual(tag.values, {"leaves": 3})
        self.assertEqual(_codes(tag.warnings), [("duplicate_key", "leaves")])
        parsed = _parse("[gate leaves=3] then [gate leaves=4] and [GATE]")
        self.assertEqual(parsed.tag("gate").values, {"leaves": 3})
        self.assertEqual(_codes(parsed.warnings), [("multiple_tags", "gate")] * 2)

    def test_a_misspelt_or_unclosed_tag_is_reported(self):
        parsed = _parse("[gaet leaves=3]")
        self.assertFalse(parsed.tag("gate").present)
        self.assertEqual(_codes(parsed.warnings), [("unknown_object", "gaet")])
        self.assertIn("[gate], [post]", parsed.warnings[0].message)
        parsed = _parse("north [gate leaves=3")
        self.assertFalse(parsed.tag("gate").present)
        self.assertEqual(_codes(parsed.warnings), [("unclosed_tag", "gate")])
        # A closed tag earlier in the notes is still used.
        parsed = _parse("[gate] and [gate leaves=3")
        self.assertTrue(parsed.tag("gate").present)
        self.assertEqual(parsed.warnings, ())

    def test_an_unclosed_tag_followed_by_another_bracket_is_reported(self):
        parsed = _parse("[gate leaves=3 see [post]")
        self.assertFalse(parsed.tag("gate").present)
        self.assertEqual(_codes(parsed.warnings), [("unclosed_tag", "gate")])
        # A later complete tag is used, but the earlier unfinished one (whose
        # values are lost) is still reported.
        parsed = _parse("[gate leaves=3 and [gate]")
        self.assertTrue(parsed.tag("gate").present)
        self.assertEqual(parsed.tag("gate").values, {})
        self.assertEqual(_codes(parsed.warnings), [("unclosed_tag", "gate")])

    def test_the_first_valid_copy_of_a_repeated_key_wins_and_warnings_say_so(self):
        tag = _parse("[gate leaves=abc leaves=3]").tag("gate")
        self.assertEqual(tag.values, {"leaves": 3})
        (warning,) = tag.warnings
        self.assertEqual(warning.code, "bad_value")
        self.assertIn("leaves=abc", warning.message)
        self.assertIn("is ignored", warning.message)
        self.assertNotIn("using 2", warning.message)
        tag = _parse("[gate leaves=9 LEAVES=3]").tag("gate")
        self.assertEqual(tag.values, {"leaves": 3})
        self.assertEqual(_codes(tag.warnings), [("out_of_range", "leaves")])
        self.assertIn("is ignored", tag.warnings[0].message)
        # With no valid copy at all, the default is used and the warnings say so.
        tag = _parse("[gate leaves=abc leaves=x]").tag("gate")
        self.assertEqual(tag.values, {})
        self.assertTrue(all("using 2" in w.message for w in tag.warnings))
        tag = _parse("[gate leaves=3 leaves=4]").tag("gate")
        self.assertEqual(tag.values, {"leaves": 3})
        self.assertIn("the first valid value is used", tag.warnings[0].message)

    def test_matching_quotes_around_a_value_are_removed(self):
        for notes in ('[gate height="6"]', "[gate height='6']", '[gate height="6 ft"]'):
            with self.subTest(notes=notes):
                tag = _parse(notes).tag("gate")
                self.assertEqual(tag.values, {"height": TagLength(6.0)})
                self.assertEqual(tag.warnings, ())
        tag = _parse("[gate height=\"6']").tag("gate")
        self.assertEqual(tag.values, {})
        self.assertEqual(_codes(tag.warnings), [("bad_value", "height")])

    def test_nested_brackets_use_the_innermost_complete_tag(self):
        parsed = _parse("[note [gate leaves=3] end]")
        self.assertEqual(parsed.tag("gate").values, {"leaves": 3})
        self.assertEqual(parsed.warnings, ())


if __name__ == "__main__":
    unittest.main()
