import unittest
from unittest import mock
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.elevation_callout import (
    ElevationCallout,
    ElevationCalloutSettings,
)
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.elevation_callout_service import (
    resolve_elevation_callout,
)
from tests.domain.services.elevation_support import (
    _area_condition as _elevation_support__area_condition,
    _area_takeoff as _elevation_support__area_takeoff,
    _outer_ring as _elevation_support__outer_ring,
)


class ElevationCalloutResolverTests(unittest.TestCase):
    def test_resolves_exact_lines_and_transformed_center(self):
        result = resolve_elevation_callout(
            _elevation_support__area_condition(
                name="F9 @T 410' 3\"", thickness=48.0, z_value=4923.0
            ),
            _elevation_support__area_takeoff(),
            [],
            _elevation_support__outer_ring(),
        )
        self.assertEqual(
            result,
            ElevationCallout(
                x=30.0,
                y=40.0,
                lines=("F9", "410' - 3\"", "406' - 3\"", "10.29 CY"),
            ),
        )

    def test_quantity_variants_remain_owned_by_canonical_quantity_logic(self):
        hole = Takeoff(
            uid="hole-1",
            condition_uid="condition-1",
            parent_uid="takeoff-1",
            position=[25.0, 25.0, 75.0, 25.0, 75.0, 75.0, 25.0, 75.0],
        )
        cases = (
            (
                "hole",
                _elevation_support__area_condition(),
                _elevation_support__area_takeoff(),
                [hole],
                "3.86 CY",
            ),
            (
                "slope",
                _elevation_support__area_condition(rise=6.0, run=12.0),
                _elevation_support__area_takeoff(),
                [],
                "5.75 CY",
            ),
            (
                "rounding",
                _elevation_support__area_condition(round_quantity=True, round_up=1.0),
                _elevation_support__area_takeoff(),
                [],
                "5.14 CY",
            ),
            (
                "negative",
                _elevation_support__area_condition(),
                _elevation_support__area_takeoff(is_negative=True),
                [],
                "-5.14 CY",
            ),
        )
        for name, condition, takeoff, holes, expected in cases:
            with self.subTest(name=name):
                result = resolve_elevation_callout(
                    condition, takeoff, holes, _elevation_support__outer_ring()
                )
                self.assertIsNotNone(result)
                self.assertEqual(result.lines[-1], expected)

    def test_bottom_reference_uses_existing_condition_elevation_direction(self):
        condition = Condition(
            uid="condition-1",
            name="Footing @B 8' 0\"",
            condition_type=Condition.TYPE_COUNT,
            width=54.0,
            height=24.0,
            depth=45.0,
            z_value=96.0,
            is_top=False,
        )
        takeoff = Takeoff(
            uid="takeoff-1",
            condition_uid="condition-1",
            page_uid="page-1",
            position=[30.0, 40.0],
        )
        result = resolve_elevation_callout(
            condition, takeoff, [], _elevation_support__outer_ring()
        )
        self.assertEqual(
            result.lines,
            ("Footing", "10' - 0\"", "8' - 0\"", "1.25 CY"),
        )

    def test_inapplicable_elevation_or_invalid_outer_ring_is_omitted(self):
        self.assertIsNone(
            resolve_elevation_callout(
                _elevation_support__area_condition(name="F9"),
                _elevation_support__area_takeoff(),
                [],
                _elevation_support__outer_ring(),
            )
        )
        self.assertIsNone(
            resolve_elevation_callout(
                _elevation_support__area_condition(),
                _elevation_support__area_takeoff(),
                [],
                _elevation_support__outer_ring(()),
            )
        )

    def test_content_settings_select_lines_in_canonical_order(self):
        result = resolve_elevation_callout(
            _elevation_support__area_condition(
                name="F9 @T 410' 3\"", thickness=48.0, z_value=4923.0
            ),
            _elevation_support__area_takeoff(),
            [],
            _elevation_support__outer_ring(),
            ElevationCalloutSettings(
                include_condition=False,
                include_top=True,
                include_bottom=False,
                include_cubic_yards=True,
            ),
        )
        self.assertEqual(result.lines, ("410' - 3\"", "10.29 CY"))

    def test_empty_content_settings_return_no_callout_without_quantity_work(self):
        with mock.patch(
            "ost_visualizer.domain.services.elevation_callout_service.compute_takeoff_cubic_yards"
        ) as quantity:
            result = resolve_elevation_callout(
                _elevation_support__area_condition(
                    name="F9 @T 410' 3\"", thickness=48.0, z_value=4923.0
                ),
                _elevation_support__area_takeoff(),
                [],
                _elevation_support__outer_ring(),
                ElevationCalloutSettings(
                    include_condition=False,
                    include_top=False,
                    include_bottom=False,
                    include_cubic_yards=False,
                ),
            )
        self.assertIsNone(result)
        quantity.assert_not_called()
