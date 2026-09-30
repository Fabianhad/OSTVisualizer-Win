import unittest
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.services.elevation import (
    format_structural_elevation,
    parse_elevation,
    reassemble_elevation,
    resolve_condition_elevation_bounds,
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
