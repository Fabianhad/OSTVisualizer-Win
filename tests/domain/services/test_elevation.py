import unittest
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.domain.services.elevation import (
    elevation_name_collisions,
    format_structural_elevation,
    parse_elevation,
    reassemble_elevation,
    resolve_condition_elevation_bounds,
    strip_elevation_suffix,
    strip_raw_condition_elevations,
)


class ParseElevationTests(unittest.TestCase):
    def test_last_explicit_marker_wins_and_legacy_marker_means_bottom(self):
        explicit = parse_elevation("Wall @T old @B 4'")
        self.assertEqual(
            (explicit.base_name, explicit.type, explicit.value),
            ("Wall @T old", 1, "4'"),
        )
        legacy = parse_elevation("Wall @ 2'")
        self.assertEqual(
            (legacy.base_name, legacy.type, legacy.value), ("Wall", 1, "2'")
        )

    def test_empty_and_unmarked_names_do_not_invent_an_elevation(self):
        self.assertEqual(parse_elevation("").value, "")
        self.assertEqual(parse_elevation("Wall").base_name, "Wall")
        self.assertEqual(reassemble_elevation("Wall", 0, " "), "Wall")
        self.assertEqual(reassemble_elevation("Wall", 1, " 2' "), "Wall @B 2'")


class ResolveConditionElevationBoundsTests(unittest.TestCase):
    def test_top_area_uses_thickness_and_bottom_linear_uses_height(self):
        area = Condition(
            uid="area",
            name="Slab @T 10'",
            condition_type=Condition.TYPE_AREA,
            z_value=120,
            thickness=6,
            height=999,
            is_top=True,
        )
        linear = Condition(
            uid="line",
            name="Wall @B 1'",
            condition_type=Condition.TYPE_LINEAR,
            z_value=12,
            height=96,
            thickness=999,
            is_top=False,
        )
        bounds = resolve_condition_elevation_bounds(area)
        self.assertEqual((bounds.top, bounds.bottom), (120, 114))
        bounds = resolve_condition_elevation_bounds(linear)
        self.assertEqual((bounds.top, bounds.bottom), (108, 12))

    def test_mismatched_marker_and_invalid_dimensions_do_not_produce_bounds(self):
        condition = Condition(
            uid="line",
            name="Wall @T 1'",
            condition_type=Condition.TYPE_LINEAR,
            z_value=12,
            height=96,
            is_top=False,
        )
        self.assertIsNone(resolve_condition_elevation_bounds(condition))
        condition.is_top = True
        for height in (0, -1, float("inf"), float("nan")):
            condition.height = height
            self.assertIsNone(resolve_condition_elevation_bounds(condition))


class FormatStructuralElevationTests(unittest.TestCase):
    def test_signed_subfoot_values_keep_explicit_zero_feet(self):
        self.assertEqual(format_structural_elevation(0), "0' - 0\"")
        self.assertEqual(format_structural_elevation(-6), "-0' - 6\"")


EXAMPLE_BASE = "(PC5__3K) (7150) (NoPiles20_Detail#) 100 098 14.5 X 11.5"


class StripElevationSuffixTests(unittest.TestCase):
    def test_the_documented_example_drops_the_elevation(self):
        name = EXAMPLE_BASE + " @T 745' 0\""
        self.assertEqual(strip_elevation_suffix(name), EXAMPLE_BASE)

    def test_xml_escaped_quotes_are_matched_like_raw_quotes(self):
        for escaped in (
            EXAMPLE_BASE + " @T 745&apos; 0&quot;",
            EXAMPLE_BASE + " @T 745&#39; 0&#34;",
            EXAMPLE_BASE + " @T 745&amp;apos; 0&amp;quot;",
            EXAMPLE_BASE + " @T 745' 0&quot;",
            EXAMPLE_BASE + ' @T 745&apos; 0"',
        ):
            with self.subTest(name=escaped):
                self.assertEqual(strip_elevation_suffix(escaped), EXAMPLE_BASE)

    def test_names_that_carry_escapes_in_the_base_keep_them(self):
        name = "Rock &amp; Fill (A&apos;s) @T 5' 0\""
        self.assertEqual(strip_elevation_suffix(name), "Rock &amp; Fill (A&apos;s)")

    def test_names_without_an_elevation_are_returned_unchanged(self):
        for name in (
            "Wall",
            EXAMPLE_BASE,
            "Footing 14.5 X 11.5",
            "Wall (A) @",
            "Wall@T 5' 0\"",
        ):
            with self.subTest(name=name):
                self.assertEqual(strip_elevation_suffix(name), name)

    def test_explicit_top_and_bottom_markers_are_dropped(self):
        self.assertEqual(strip_elevation_suffix("Wall @B 8' 0\""), "Wall")
        self.assertEqual(strip_elevation_suffix("Wall @T 8' 0\""), "Wall")

    def test_the_legacy_marker_is_never_stripped_so_ordinary_text_survives(self):
        for name in (
            "Wall @ 9' 0\"",
            'Rebar #5 @ 12" OC',
            'Cut @ 12" o.c.',
            'Anchor @ 6"',
            'Rebar #5 @ 12" each way',
            "Footing @ 3 ft",
            "Email me @ 12 in",
            "name@example.com",
            "Slab @ 1m 20cm",
        ):
            with self.subTest(name=name):
                self.assertEqual(strip_elevation_suffix(name), name)

    def test_an_explicit_elevation_after_legacy_looking_text_still_strips(self):
        self.assertEqual(
            strip_elevation_suffix('Rebar #5 @ 12" OC @T 5\' 0"'),
            'Rebar #5 @ 12" OC',
        )

    def test_feet_inches_variants(self):
        for value in (
            "745' 0\"",
            "12' 6 1/2\"",
            "12'-6\"",
            "12' 6\"",
            "5'",
            "5&apos;",
            '6"',
            '1/2"',
            '3 1/2"',
            "-4' 2\"",
            '410′ 3"',
        ):
            with self.subTest(value=value):
                self.assertEqual(strip_elevation_suffix("Wall @T " + value), "Wall")

    def test_metric_variants(self):
        for value in (
            "1m 20cm",
            "1m and 20cm",
            "1m+20cm",
            "2,5 m",
            "2.5 meters",
            "30 cm",
        ):
            with self.subTest(value=value):
                self.assertEqual(strip_elevation_suffix("Wall @B " + value), "Wall")

    def test_a_marker_that_is_not_followed_by_an_elevation_is_not_an_elevation(self):
        for name in (
            "Meeting @T later",
            "Wall @T 5pm",
            "Wall @B",
            "Wall @T ",
            "Email @ home",
            "Wall @T junk @B more junk",
        ):
            with self.subTest(name=name):
                self.assertEqual(strip_elevation_suffix(name), name)

    def test_marker_text_elsewhere_in_the_name_is_kept(self):
        self.assertEqual(
            strip_elevation_suffix("Hook @T Hangers 100 @T 5' 0\""),
            "Hook @T Hangers 100",
        )
        self.assertEqual(strip_elevation_suffix("Wall @T old @B 4' 0\""), "Wall @T old")
        self.assertEqual(
            strip_elevation_suffix("Rail (see @T notes) @B 3' 0\""),
            "Rail (see @T notes)",
        )

    def test_a_valid_elevation_takes_everything_after_the_marker_with_it(self):
        self.assertEqual(strip_elevation_suffix("A @T 5' 0\" extra text"), "A")

    def test_only_the_last_elevation_is_dropped(self):
        for name, expected in (
            ("Tower @T 40' 0\" @B 2' 0\"", "Tower @T 40' 0\""),
            ("Wall @T 4' @T 5'", "Wall @T 4'"),
            ("Wall @T 4' 0\" @T 5' 0\"", "Wall @T 4' 0\""),
            ("Wall @B 4' 0\" @T 5' 0\"", "Wall @B 4' 0\""),
        ):
            with self.subTest(name=name):
                self.assertEqual(strip_elevation_suffix(name), expected)
                self.assertEqual(
                    strip_elevation_suffix(name), parse_elevation(name).base_name
                )

    def test_a_name_that_carries_two_elevations_loses_one_per_call(self):
        once = strip_elevation_suffix("Wall @T 4' @T 5'")
        self.assertEqual(once, "Wall @T 4'")
        self.assertEqual(strip_elevation_suffix(once), "Wall")

    def test_surrounding_whitespace_does_not_leak_into_the_result(self):
        self.assertEqual(strip_elevation_suffix("Wall   @T 5' 0\"  "), "Wall")

    def test_empty_blank_and_elevation_only_names_are_returned_unchanged(self):
        for name in ("", " ", " @T 5' 0\"", " @B 12' 6 1/2\""):
            with self.subTest(name=name):
                self.assertEqual(strip_elevation_suffix(name), name)

    def test_the_function_is_idempotent(self):
        for name in (
            EXAMPLE_BASE + " @T 745' 0\"",
            EXAMPLE_BASE + " @T 745&apos; 0&quot;",
            "Wall @T old @B 4' 0\"",
            'Rebar #5 @ 12" OC',
            'Rebar #5 @ 12" OC @T 5\' 0"',
            "Meeting @T later",
            "",
            "Wall",
        ):
            with self.subTest(name=name):
                once = strip_elevation_suffix(name)
                self.assertEqual(strip_elevation_suffix(once), once)

    def test_the_condition_object_is_never_touched_by_stripping_its_name(self):
        condition = Condition(uid="1", name="Wall @T 5' 0\"", z_value=60.0, is_top=True)
        stripped = strip_elevation_suffix(condition.name)
        self.assertEqual(stripped, "Wall")
        self.assertEqual(
            (condition.name, condition.z_value, condition.is_top),
            ("Wall @T 5' 0\"", 60.0, True),
        )


class ElevationNameCollisionTests(unittest.TestCase):
    def test_names_that_only_differ_by_elevation_collide(self):
        names = ["Wall @T 5' 0\"", "Wall @B 2' 0\"", "Slab @T 1' 0\"", "Slab"]
        self.assertEqual(elevation_name_collisions(names), [("Wall", 2), ("Slab", 2)])

    def test_conditions_that_already_share_a_name_are_not_reported(self):
        self.assertEqual(
            elevation_name_collisions(["Wall", "Wall", "Slab @T 1' 0\""]), []
        )
        self.assertEqual(
            elevation_name_collisions(["Wall @T 5' 0\"", "Wall @T 5' 0\""]), []
        )

    def test_distinct_names_do_not_collide(self):
        self.assertEqual(
            elevation_name_collisions(["A @T 1' 0\"", "B @T 1' 0\"", "C"]), []
        )

    def test_empty_input(self):
        self.assertEqual(elevation_name_collisions([]), [])

    def test_the_count_includes_every_condition_even_with_repeated_names(self):
        names = ["Wall @T 5' 0\"", "Wall @T 5' 0\"", "Wall @B 2' 0\""]
        self.assertEqual(elevation_name_collisions(names), [("Wall", 3)])

    def test_collisions_keep_first_seen_order_and_count_every_condition(self):
        names = ["B @T 1' 0\"", "A @T 1' 0\"", "B @B 2' 0\"", "A", "B"]
        self.assertEqual(elevation_name_collisions(names), [("B", 3), ("A", 2)])


def _raw_bid_data():
    return RawBidData(
        bid_row={"UID": "bid", "Name": "Bid @T 5' 0\""},
        bid_tables={
            "BidConditions": [
                {"UID": "1", "Name": "Wall @T 5' 0\"", "Type": "0"},
                {"UID": "2", "Name": "Wall @B 2&apos; 0&quot;", "Type": "0"},
                {"UID": "3", "Name": "Plain", "Type": "0"},
                {"UID": "4", "Name": "NULL", "Type": "0"},
                {"UID": "5", "Type": "0"},
            ],
            "BidConditionFolders": [{"UID": "f", "Name": "Level @T 9' 0\""}],
            "BidPages": [{"UID": "p", "Name": "Sheet @T 1' 0\""}],
        },
        page_tables={"BidTakeoffs": [{"UID": "t", "ConditionUID": "1"}]},
        global_tables={"CdnTypes": [{"UID": "c", "Name": "Type @B 1' 0\""}]},
    )


class StripRawConditionElevationsTests(unittest.TestCase):
    def test_condition_names_lose_their_elevation_and_nothing_else_changes(self):
        stripped = strip_raw_condition_elevations(_raw_bid_data())
        self.assertEqual(
            [row.get("Name") for row in stripped.bid_tables["BidConditions"]],
            ["Wall", "Wall", "Plain", "NULL", None],
        )
        self.assertEqual(
            [row["UID"] for row in stripped.bid_tables["BidConditions"]],
            ["1", "2", "3", "4", "5"],
        )
        expected = _raw_bid_data()
        self.assertEqual(stripped.bid_row, expected.bid_row)
        self.assertEqual(
            stripped.bid_tables["BidConditionFolders"],
            expected.bid_tables["BidConditionFolders"],
        )
        self.assertEqual(
            stripped.bid_tables["BidPages"], expected.bid_tables["BidPages"]
        )
        self.assertEqual(stripped.page_tables, expected.page_tables)
        self.assertEqual(stripped.global_tables, expected.global_tables)

    def test_the_source_data_is_never_modified(self):
        source = _raw_bid_data()
        stripped = strip_raw_condition_elevations(source)
        self.assertEqual(source.bid_tables, _raw_bid_data().bid_tables)
        self.assertIsNot(stripped, source)
        self.assertIsNot(stripped.bid_tables, source.bid_tables)
        self.assertIsNot(
            stripped.bid_tables["BidConditions"], source.bid_tables["BidConditions"]
        )
        for new_row, old_row in zip(
            stripped.bid_tables["BidConditions"], source.bid_tables["BidConditions"]
        ):
            self.assertIsNot(new_row, old_row)

    def test_unrelated_tables_are_shared_not_copied(self):
        source = _raw_bid_data()
        stripped = strip_raw_condition_elevations(source)
        self.assertIs(
            stripped.bid_tables["BidConditionFolders"],
            source.bid_tables["BidConditionFolders"],
        )
        self.assertIs(stripped.page_tables, source.page_tables)
        self.assertIs(stripped.global_tables, source.global_tables)

    def test_data_without_a_conditions_table_is_returned_as_an_equal_copy(self):
        source = RawBidData(bid_row={"UID": "bid"}, bid_tables={})
        stripped = strip_raw_condition_elevations(source)
        self.assertEqual(stripped, source)
        self.assertIsNot(stripped, source)

    def test_stripping_twice_gives_the_same_names(self):
        once = strip_raw_condition_elevations(_raw_bid_data())
        twice = strip_raw_condition_elevations(once)
        self.assertEqual(once, twice)

    def test_collisions_can_be_computed_from_the_untouched_rows(self):
        names = [
            row.get("Name", "") for row in _raw_bid_data().bid_tables["BidConditions"]
        ]
        self.assertEqual(elevation_name_collisions(names), [("Wall", 2)])


class ParseElevationTableTests(unittest.TestCase):
    def parsed(self, name):
        parts = parse_elevation(name)
        return parts.base_name, parts.type, parts.value

    def test_each_marker_form_splits_into_base_type_and_value(self):
        table = (
            ("Wall @T 10'", ("Wall", 0, "10'")),
            ("Wall @B 10'", ("Wall", 1, "10'")),
            ("Wall @T10'", ("Wall", 0, "10'")),
            ("Wall @B10'", ("Wall", 1, "10'")),
            ("Wall @T", ("Wall", 0, "")),
            ("Wall @B", ("Wall", 1, "")),
            ("Wall @T ", ("Wall", 0, "")),
            ("Wall @ 2'", ("Wall", 1, "2'")),
            ("Wall @2'", ("Wall", 1, "2'")),
            ("Wall @", ("Wall", 1, "")),
            ("Wall @ ", ("Wall", 1, "")),
            ("Wall", ("Wall", 0, "")),
            ("", ("", 0, "")),
            ("@T 5'", ("@T 5'", 0, "")),
            (" @T 5'", ("", 0, "5'")),
        )
        for name, expected in table:
            with self.subTest(name=name):
                self.assertEqual(self.parsed(name), expected)

    def test_the_marker_that_appears_last_wins_and_an_explicit_marker_beats_the_legacy_one(self):
        self.assertEqual(self.parsed("A @B 1' @T 2'"), ("A @B 1'", 0, "2'"))
        self.assertEqual(self.parsed("A @T 1' @B 2'"), ("A @T 1'", 1, "2'"))
        self.assertEqual(self.parsed("A @ 1' @T 2'"), ("A @ 1'", 0, "2'"))
        self.assertEqual(self.parsed("A @T 2' @ 3'"), ("A", 0, "2' @ 3'"))
        self.assertEqual(self.parsed("A @ 2' @x"), ("A", 1, "2' @x"))

    def test_only_one_separating_space_after_the_marker_is_dropped(self):
        self.assertEqual(self.parsed("A @T  2'"), ("A", 0, " 2'"))
        self.assertEqual(self.parsed("A @B   x"), ("A", 1, "  x"))

    def test_elevation_parts_default_to_an_empty_top_elevation(self):
        from ost_visualizer.domain.services.elevation import ElevationParts

        parts = ElevationParts()
        self.assertEqual((parts.base_name, parts.type, parts.value), ("", 0, ""))

    def test_reassembly_uses_the_marker_for_the_type_and_trims_the_value(self):
        self.assertEqual(reassemble_elevation("Wall", 0, "10'"), "Wall @T 10'")
        self.assertEqual(reassemble_elevation("Wall", 1, "10'"), "Wall @B 10'")
        self.assertEqual(reassemble_elevation("Wall", 5, "10'"), "Wall @B 10'")
        self.assertEqual(reassemble_elevation("Wall", 0, "  "), "Wall")
        self.assertEqual(reassemble_elevation("", 0, "1'"), " @T 1'")
        name = reassemble_elevation("Wall", 0, " 10' 3\" ")
        self.assertEqual(parse_elevation(name).value, "10' 3\"")


class FormatStructuralElevationTableTests(unittest.TestCase):
    def test_values_are_shown_as_feet_dash_inches_with_a_sign_and_eighths(self):
        for value, text in (
            (12, "1' - 0\""),
            (13, "1' - 1\""),
            (18, "1' - 6\""),
            (24.5, "2' - 0 1/2\""),
            (30.125, "2' - 6 1/8\""),
            (-12, "-1' - 0\""),
            (-13.5, "-1' - 1 1/2\""),
            (5, "0' - 5\""),
            (5.5, "0' - 5 1/2\""),
            (0.125, "0' - 1/8\""),
            (-0.5, "-0' - 1/2\""),
            (0.0, "0' - 0\""),
            (0.01, "0' - 0\""),
            (745 * 12, "745' - 0\""),
        ):
            with self.subTest(value=value):
                self.assertEqual(format_structural_elevation(value), text)


class ResolveBoundsDetailTests(unittest.TestCase):
    def condition(self, **changes):
        base = dict(
            uid="c",
            name="Wall @T 10'",
            condition_type=Condition.TYPE_LINEAR,
            z_value=100.0,
            height=20.0,
            thickness=5.0,
            is_top=True,
        )
        base.update(changes)
        return Condition(**base)

    def test_top_marker_measures_down_and_bottom_marker_measures_up_from_the_reference(self):
        top = resolve_condition_elevation_bounds(self.condition())
        self.assertEqual((top.base_name, top.top, top.bottom), ("Wall", 100.0, 80.0))
        bottom = resolve_condition_elevation_bounds(
            self.condition(name="Wall @B 10'", is_top=False)
        )
        self.assertEqual((bottom.base_name, bottom.top, bottom.bottom), ("Wall", 120.0, 100.0))

    def test_base_name_is_trimmed_and_blank_values_give_no_bounds(self):
        bounds = resolve_condition_elevation_bounds(self.condition(name="  Wall   @T 10'"))
        self.assertEqual(bounds.base_name, "Wall")
        for name in ("Wall", "Wall @T", "Wall @T   ", ""):
            with self.subTest(name=name):
                self.assertIsNone(resolve_condition_elevation_bounds(self.condition(name=name)))

    def test_count_and_attachment_conditions_use_height_and_area_uses_thickness(self):
        for condition_type in (Condition.TYPE_COUNT, Condition.TYPE_ATTACHMENT, Condition.TYPE_LINEAR):
            bounds = resolve_condition_elevation_bounds(self.condition(condition_type=condition_type))
            self.assertEqual(bounds.bottom, 80.0)
        area = resolve_condition_elevation_bounds(self.condition(condition_type=Condition.TYPE_AREA))
        self.assertEqual(area.bottom, 95.0)

    def test_non_finite_reference_and_tiny_positive_sizes(self):
        for reference in (float("nan"), float("inf"), float("-inf")):
            self.assertIsNone(
                resolve_condition_elevation_bounds(self.condition(z_value=reference))
            )
        bounds = resolve_condition_elevation_bounds(self.condition(height=0.5))
        self.assertEqual((bounds.top, bounds.bottom), (100.0, 99.5))
        self.assertIsNone(resolve_condition_elevation_bounds(self.condition(height=0.0)))

    def test_a_truthy_is_top_flag_selects_the_top_marker(self):
        self.assertIsNotNone(resolve_condition_elevation_bounds(self.condition(is_top=1)))
        self.assertIsNone(resolve_condition_elevation_bounds(self.condition(is_top=0)))


class StripElevationEscapeDepthTests(unittest.TestCase):
    def test_escapes_are_decoded_at_most_twice_when_judging_the_elevation_text(self):
        # &amp;apos; is decoded twice and is feet; one more level is plain text.
        self.assertEqual(strip_elevation_suffix("Wall @T 5&amp;apos;"), "Wall")
        triple = "Wall @T 5&amp;amp;apos;"
        self.assertEqual(strip_elevation_suffix(triple), triple)

    def test_a_name_that_starts_with_the_marker_keeps_its_text(self):
        for name in ("@T 5'", "@B 5'"):
            self.assertEqual(strip_elevation_suffix(name), name)
        self.assertEqual(strip_elevation_suffix(" @T 5'"), " @T 5'")


class ElevationBoundsValueTests(unittest.TestCase):
    def test_bounds_are_immutable_values(self):
        from dataclasses import FrozenInstanceError
        from ost_visualizer.domain.services.elevation import ConditionElevationBounds

        bounds = ConditionElevationBounds("Wall", 10.0, 2.0)
        with self.assertRaises(FrozenInstanceError):
            bounds.top = 11.0
        self.assertEqual(bounds, ConditionElevationBounds("Wall", 10.0, 2.0))
