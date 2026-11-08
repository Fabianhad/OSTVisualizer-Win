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

    def test_an_unsupported_condition_type_keeps_the_callout_but_drops_the_quantity(
        self,
    ):
        for condition_type in (4, 99):
            with self.subTest(condition_type=condition_type):
                with self.assertLogs(
                    "ost_visualizer.domain.services.elevation_callout_service",
                    level="WARNING",
                ) as logged:
                    result = resolve_elevation_callout(
                        _elevation_support__area_condition(
                            name="F9 @T 410' 3\"",
                            thickness=48.0,
                            height=48.0,
                            z_value=4923.0,
                            condition_type=condition_type,
                        ),
                        _elevation_support__area_takeoff(),
                        [],
                        _elevation_support__outer_ring(),
                    )
                self.assertIsNotNone(result)
                self.assertEqual((result.x, result.y), (30.0, 40.0))
                self.assertEqual(result.lines[0], "F9")
                self.assertTrue(all("CY" not in line for line in result.lines))
                message = logged.records[0].getMessage()
                self.assertIn("condition-1", message)
                self.assertIn(str(condition_type), message)

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


class ElevationCalloutCenterTests(unittest.TestCase):
    def resolve(self, ring):
        return resolve_elevation_callout(
            _elevation_support__area_condition(
                name="F9 @T 410' 3\"", thickness=48.0, z_value=4923.0
            ),
            _elevation_support__area_takeoff(),
            [],
            tuple(ring),
            ElevationCalloutSettings(
                include_condition=True,
                include_top=False,
                include_bottom=False,
                include_cubic_yards=False,
            ),
        )

    def test_center_is_the_middle_of_the_bounding_box_of_the_finite_points_only(self):
        nan, inf = float("nan"), float("inf")
        result = self.resolve(
            [(0, 0), (10, 20), (nan, 5), (5, nan), (inf, 3), (4, -inf), (-inf, -inf)]
        )
        self.assertEqual((result.x, result.y, result.lines), (5.0, 10.0, ("F9",)))

    def test_center_uses_the_bounding_box_not_the_vertex_average(self):
        result = self.resolve([(0, 0), (1, 0), (1, 1), (0, 1), (9, 5)])
        self.assertEqual((result.x, result.y), (4.5, 2.5))
        negative = self.resolve([(-10, -4), (-2, -8)])
        self.assertEqual((negative.x, negative.y), (-6.0, -6.0))

    def test_rings_without_any_finite_point_have_no_callout(self):
        nan, inf = float("nan"), float("inf")
        self.assertIsNone(self.resolve([(nan, 1), (1, inf), (inf, nan)]))
        self.assertIsNone(self.resolve([]))

    def test_a_single_finite_point_is_its_own_center_and_numeric_text_is_accepted(self):
        result = self.resolve([(3, 4)])
        self.assertEqual((result.x, result.y), (3.0, 4.0))
        self.assertIsInstance(result.x, float)


class ElevationCalloutQuantityFailureTests(unittest.TestCase):
    SERVICE = "ost_visualizer.domain.services.elevation_callout_service"

    def resolve(self):
        return resolve_elevation_callout(
            _elevation_support__area_condition(
                name="F9 @T 410' 3\"",
                thickness=48.0,
                height=48.0,
                z_value=4923.0,
                condition_type=99,
            ),
            _elevation_support__area_takeoff(),
            [],
            _elevation_support__outer_ring(),
        )

    def test_the_dropped_quantity_is_logged_once_with_the_condition_and_the_reason(
        self,
    ):
        with self.assertLogs(self.SERVICE, level="WARNING") as logged:
            result = self.resolve()
        self.assertEqual(result.lines, ("F9", "410' - 3\"", "406' - 3\""))
        self.assertEqual(len(logged.records), 1)
        self.assertEqual(logged.records[0].levelname, "WARNING")
        self.assertEqual(
            logged.records[0].getMessage(),
            "Omitting cubic yards from the elevation callout of condition "
            "condition-1 ('F9 @T 410\\' 3\"'): Unsupported condition type 99",
        )

    def test_only_a_value_error_from_the_quantity_is_absorbed(self):
        with mock.patch(
            self.SERVICE + ".compute_takeoff_cubic_yards",
            side_effect=RuntimeError("quantity engine broke"),
        ):
            with self.assertRaisesRegex(RuntimeError, "quantity engine broke"):
                self.resolve()

    def test_the_quantity_line_is_the_two_decimal_cubic_yards_with_the_uom_label(
        self,
    ):
        with mock.patch(
            self.SERVICE + ".compute_takeoff_cubic_yards", return_value=2.0049
        ) as quantity:
            result = self.resolve()
        self.assertEqual(result.lines[-1], "2.00 CY")
        quantity.assert_called_once()
        self.assertEqual(quantity.call_args.args[2], [])

    def test_ring_coordinates_are_coerced_to_float_characterisation(self):
        from decimal import Decimal

        result = resolve_elevation_callout(
            _elevation_support__area_condition(
                name="F9 @T 410' 3\"", thickness=48.0, z_value=4923.0
            ),
            _elevation_support__area_takeoff(),
            [],
            ((Decimal("1"), Decimal("2")), (Decimal("5"), Decimal("8"))),
            ElevationCalloutSettings(
                include_condition=True,
                include_top=False,
                include_bottom=False,
                include_cubic_yards=False,
            ),
        )
        self.assertEqual((result.x, result.y), (3.0, 5.0))
        self.assertIsInstance(result.x, float)
        self.assertIsInstance(result.y, float)


class ElevationCalloutValueTests(unittest.TestCase):
    def test_settings_and_callouts_are_immutable_values(self):
        from dataclasses import FrozenInstanceError

        settings = ElevationCalloutSettings()
        with self.assertRaises(FrozenInstanceError):
            settings.include_top = False
        callout = ElevationCallout(x=1.0, y=2.0, lines=("F9",))
        with self.assertRaises(FrozenInstanceError):
            callout.x = 5.0
        self.assertEqual(callout, ElevationCallout(x=1.0, y=2.0, lines=("F9",)))
        self.assertEqual((callout.x, callout.y, callout.lines), (1.0, 2.0, ("F9",)))

    def test_each_content_flag_alone_keeps_the_callout_and_all_off_has_no_content(
        self,
    ):
        flags = (
            "include_condition",
            "include_top",
            "include_bottom",
            "include_cubic_yards",
        )
        self.assertTrue(ElevationCalloutSettings().has_content)
        for enabled in flags:
            with self.subTest(enabled=enabled):
                settings = ElevationCalloutSettings(
                    **{flag: flag == enabled for flag in flags}
                )
                self.assertTrue(settings.has_content)
        self.assertFalse(
            ElevationCalloutSettings(**{flag: False for flag in flags}).has_content
        )
