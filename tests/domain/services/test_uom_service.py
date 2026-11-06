import math
import unittest
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.services.uom_service import (
    CALC_LINEAR_LENGTH,
    UOM_INCHES,
    UOM_SQUARE_FEET,
    calculate_condition_quantities,
)


class UomServiceTests(unittest.TestCase):
    def test_axis_aligned_circular_curve_uses_its_arc_length(self):
        quantity, _quantity2, _quantity3 = calculate_condition_quantities(
            condition_type=Condition.TYPE_LINEAR,
            calc_type1=CALC_LINEAR_LENGTH,
            calc_type2=0,
            calc_type3=0,
            uom1=UOM_INCHES,
            uom2=UOM_INCHES,
            uom3=UOM_INCHES,
            width=0.0,
            height=0.0,
            depth=0.0,
            thickness=0.0,
            position=[1.0, 0.0, 0.0, 1.0, 1.0, 1.0],
            curve=0,
        )
        self.assertAlmostEqual(quantity, math.pi / math.sqrt(2.0), delta=0.03)


class AreaSlopeBehaviorTests(unittest.TestCase):
    def test_area_quantity_retains_fractional_origin_precision(self):
        q1, _q2, _q3 = calculate_condition_quantities(
            Condition.TYPE_AREA,
            11,
            0,
            0,
            UOM_SQUARE_FEET,
            0,
            0,
            width=0,
            height=0,
            depth=0,
            thickness=0,
            position=[
                891.672,
                507.397,
                435.672,
                507.397,
                435.672,
                860.397,
                593.672,
                860.397,
                593.672,
                702.397,
                893.672,
                702.397,
            ],
        )
        # Independent decomposition after subtracting the fractional origin:
        # 458 x 195 rectangle, minus the 2 x 195 / 2 right-edge triangle,
        # plus the 158 x 158 lower-left rectangle. Convert square inches to feet.
        expected_square_feet = (458 * 195 - 2 * 195 / 2 + 158 * 158) / 144
        self.assertAlmostEqual(q1, expected_square_feet, places=10)

    def test_area_quantity_uses_absolute_slope_magnitude(self):
        q1, _q2, _q3 = calculate_condition_quantities(
            Condition.TYPE_AREA,
            11,
            0,
            0,
            UOM_SQUARE_FEET,
            0,
            0,
            width=0,
            height=0,
            depth=0,
            thickness=0,
            position=[0, 0, 120, 0, 120, 120, 0, 120],
            rise=-3,
            run=4,
        )
        self.assertAlmostEqual(q1, 125.0)


from ost_visualizer.domain.services import uom_service as uom


def _quantities(condition_type, calc_type, uom_code=0, **kwargs):
    values = dict(
        condition_type=condition_type,
        calc_type1=calc_type,
        calc_type2=0,
        calc_type3=0,
        uom1=uom_code,
        uom2=0,
        uom3=0,
        width=0.0,
        height=0.0,
        depth=0.0,
        thickness=0.0,
    )
    values.update(kwargs)
    return uom.calculate_condition_quantities(**values)


SQUARE_12 = [0, 0, 12, 0, 12, 12, 0, 12]
HOLE_6 = [0, 0, 6, 0, 6, 6, 0, 6]


class UomCodeTableTests(unittest.TestCase):
    def test_uom_and_calculation_codes_are_the_stored_database_values(self):
        self.assertEqual(
            [
                uom.UOM_EACH,
                uom.UOM_INCHES,
                uom.UOM_LINEAR_FEET,
                uom.UOM_LINEAR_YARDS,
                uom.UOM_SQUARE_INCHES,
                uom.UOM_SQUARE_FEET,
                uom.UOM_SQUARE_YARDS,
                uom.UOM_SQUARE_ROOFING,
                uom.UOM_CUBIC_FEET,
                uom.UOM_CUBIC_YARDS,
                uom.UOM_MM,
                uom.UOM_MM2,
                uom.UOM_M,
                uom.UOM_M2,
                uom.UOM_MM3,
                uom.UOM_M3,
            ],
            [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16],
        )
        self.assertEqual(
            [
                uom.CALC_TOP_BOTTOM,
                uom.CALC_TOP_AND_BOTTOM,
                uom.CALC_LINEAR_LENGTH,
                uom.CALC_LINEAR_BOTH_SIDES,
                uom.CALC_LINEAR_BOTH_ENDS,
                uom.CALC_AREA,
                uom.CALC_AREA_PERIMETER,
                uom.CALC_VOLUME,
                uom.CALC_AREA_VOLUME,
                uom.CALC_COUNT,
                uom.CALC_HEIGHT_OR_LENGTH,
                uom.CALC_WIDTH_SIDE,
                uom.CALC_BOTH_WIDTH_SIDES,
                uom.CALC_DEPTH_SIDE,
                uom.CALC_BOTH_DEPTH_SIDES,
                uom.CALC_ALL_SIDES,
                uom.CALC_ALL_SIDES_PLUS_TB,
            ],
            [5, 6, 1, 4, 8, 11, 15, 20, 21, 23, 24, 25, 26, 27, 28, 29, 30],
        )

    def test_labels_cover_every_uom_and_unknown_codes_have_no_label(self):
        expected = {
            0: "EA", 1: "IN", 2: "LF", 3: "LY", 4: "IN²", 5: "SF", 6: "SY",
            7: "SQ", 8: "CF", 9: "CY", 11: "mm", 12: "mm²", 13: "m",
            14: "m²", 15: "mm³", 16: "m³",
        }
        self.assertEqual(uom.UOM_LABELS, expected)
        for code, label in expected.items():
            self.assertEqual(uom.get_uom_label(code), label)
        for code in (10, 17, -1, 99):
            self.assertEqual(uom.get_uom_label(code), "")

    def test_only_the_millimetre_and_metre_families_are_metric(self):
        for code in range(0, 20):
            self.assertIs(uom.is_metric_uom(code), code in (11, 12, 13, 14, 15, 16))

    def test_quantity_option_lists_are_the_dialog_contract(self):
        self.assertEqual(
            uom.COUNT_QUANTITY_OPTIONS,
            [
                (23, "Count"),
                (24, "Total Height"),
                (13, "Perimeter"),
                (5, "Surface area (top or bottom)"),
                (6, "Surface area (top and bottom)"),
                (25, "Surface area (single width side)"),
                (26, "Surface area (both width sides)"),
                (29, "Surface area (all sides)"),
                (30, "Surface area (all sides + top and bottom)"),
                (20, "Volume"),
            ],
        )
        self.assertEqual(
            uom.LINEAR_QUANTITY_OPTIONS,
            [
                (1, "Length"),
                (2, "Segment count"),
                (3, "Surface area (single side)"),
                (4, "Surface area (both sides)"),
                (5, "Surface area (top or bottom)"),
                (6, "Surface area (top and bottom)"),
                (7, "Surface area (single end)"),
                (8, "Surface area (both ends)"),
                (9, "Surface area (all side/duct)"),
                (20, "Volume"),
            ],
        )
        self.assertEqual(
            uom.AREA_QUANTITY_OPTIONS,
            [
                (11, "Area"),
                (34, "Area (Ignore Backout Areas)"),
                (12, "Area (minus Attachments)"),
                (15, "Perimeter"),
                (14, "Perimeter (without Backout Perimeters)"),
                (33, "Perimeter (plus Attachments Perimeter)"),
                (16, "Grid length (visible)"),
                (17, "Tile count (average)"),
                (18, "Tile count (visible)"),
                (19, "Area counts"),
                (21, "Volume"),
                (35, "Volume (Ignore Backout Volume)"),
                (22, "Volume (minus Attachments)"),
            ],
        )

    def test_options_depend_on_condition_type_and_unknown_types_get_count_options(self):
        self.assertIs(
            uom.get_quantity_options_for_type(Condition.TYPE_COUNT),
            uom.COUNT_QUANTITY_OPTIONS,
        )
        self.assertIs(
            uom.get_quantity_options_for_type(Condition.TYPE_LINEAR),
            uom.LINEAR_QUANTITY_OPTIONS,
        )
        self.assertIs(
            uom.get_quantity_options_for_type(Condition.TYPE_AREA),
            uom.AREA_QUANTITY_OPTIONS,
        )
        for other in (Condition.TYPE_ATTACHMENT, 9, -1):
            self.assertIs(
                uom.get_quantity_options_for_type(other), uom.COUNT_QUANTITY_OPTIONS
            )

    def test_every_offered_calculation_maps_to_the_unit_family_its_label_measures(self):
        count = [(0, "EA")]
        length = [(2, "LF"), (3, "LY"), (1, "IN")]
        area = [(5, "SF"), (6, "SY"), (7, "SQ"), (4, "IN\u00b2")]
        volume = [(8, "CF"), (9, "CY")]
        length_m = [(13, "m"), (11, "mm")]
        area_m = [(14, "m\u00b2"), (12, "mm\u00b2")]
        volume_m = [(16, "m\u00b3"), (15, "mm\u00b3")]

        def expected(label):
            # Independent of the production tables: what does the label measure?
            low = label.lower()
            if low in ("count", "segment count", "area counts") or low.startswith(
                "tile count"
            ):
                return count, count
            if "volume" in low:
                return volume, volume_m
            if "surface area" in low or low.startswith("area"):
                return area, area_m
            return length, length_m  # length, perimeter, total height, grid length

        seen = 0
        for options in (
            uom.COUNT_QUANTITY_OPTIONS,
            uom.LINEAR_QUANTITY_OPTIONS,
            uom.AREA_QUANTITY_OPTIONS,
        ):
            self.assertEqual(len({calc for calc, _label in options}), len(options))
            for calc_type, label in options:
                seen += 1
                imperial, metric = expected(label)
                with self.subTest(calc_type=calc_type, label=label):
                    self.assertEqual(uom.get_valid_uoms_for_calc_type(calc_type), imperial)
                    self.assertEqual(
                        uom.get_valid_uoms_for_calc_type(calc_type, metric=True), metric
                    )
        self.assertEqual(seen, 33)
        self.assertEqual(uom.get_valid_uoms_for_calc_type(0), [(0, "EA")])
        self.assertEqual(uom.get_valid_uoms_for_calc_type(0, metric=True), [(0, "EA")])


class UomValidUnitTests(unittest.TestCase):
    COUNT = [(0, "EA")]
    LENGTH = [(2, "LF"), (3, "LY"), (1, "IN")]
    AREA = [(5, "SF"), (6, "SY"), (7, "SQ"), (4, "IN²")]
    VOLUME = [(8, "CF"), (9, "CY")]
    LENGTH_M = [(13, "m"), (11, "mm")]
    AREA_M = [(14, "m²"), (12, "mm²")]
    VOLUME_M = [(16, "m³"), (15, "mm³")]

    def test_every_calculation_code_selects_its_unit_family_in_both_systems(self):
        families = {}
        for code in (0, 23, 2, 17, 18, 19):
            families[code] = (self.COUNT, self.COUNT)
        for code in (1, 24, 13, 14, 15, 16, 33):
            families[code] = (self.LENGTH, self.LENGTH_M)
        for code in (20, 21, 22, 35):
            families[code] = (self.VOLUME, self.VOLUME_M)
        for code in (5, 6, 25, 26, 27, 28, 29, 30, 3, 4, 7, 8, 9, 11, 12, 34):
            families[code] = (self.AREA, self.AREA_M)
        for code in (10, 31, 32, 36, 99, -1):
            families[code] = (self.LENGTH, self.LENGTH_M)
        for code, (imperial, metric) in families.items():
            with self.subTest(calc_type=code):
                self.assertEqual(uom.get_valid_uoms_for_calc_type(code), imperial)
                self.assertEqual(uom.get_valid_uoms_for_calc_type(code, True), metric)
                self.assertEqual(
                    uom.get_valid_uoms_for_calc_type(code, metric=False), imperial
                )

    def test_system_normalization_maps_each_unit_to_its_counterpart(self):
        imperial_to_metric = {1: 13, 2: 13, 3: 13, 4: 14, 5: 14, 6: 14, 7: 14, 8: 16, 9: 16}
        for code, expected in imperial_to_metric.items():
            with self.subTest(code=code):
                self.assertEqual(uom.normalize_uom_for_system(code, True), expected)
                self.assertEqual(uom.normalize_uom_for_system(code, False), code)
        metric_to_imperial = {11: 2, 13: 2, 12: 5, 14: 5, 15: 8, 16: 8}
        for code, expected in metric_to_imperial.items():
            with self.subTest(code=code):
                self.assertEqual(uom.normalize_uom_for_system(code, False), expected)
                self.assertEqual(uom.normalize_uom_for_system(code, True), code)
        for code in (0, 10, 99):
            self.assertEqual(uom.normalize_uom_for_system(code, True), code)
            self.assertEqual(uom.normalize_uom_for_system(code, False), code)

    def test_tuple_normalization_applies_per_element(self):
        self.assertEqual(uom.normalize_uoms_for_system((2, 5, 0), True), (13, 14, 0))
        self.assertEqual(uom.normalize_uoms_for_system((13, 14, 0), False), (2, 5, 0))
        self.assertEqual(uom.normalize_uoms_for_system((), True), ())

    def test_calculation_normalization_keeps_valid_units_and_falls_back_to_the_first_valid(self):
        norm = uom.normalize_uom_for_calculation
        # calc type 0 only converts between systems.
        self.assertEqual(norm(0, 2, True), 13)
        self.assertEqual(norm(0, 13, False), 2)
        # An area calculation keeps a valid area unit, converts a metric one and
        # replaces a length unit with the first area unit.
        self.assertEqual(norm(uom.CALC_AREA, uom.UOM_SQUARE_YARDS, False), 6)
        self.assertEqual(norm(uom.CALC_AREA, uom.UOM_SQUARE_YARDS, True), 14)
        self.assertEqual(norm(uom.CALC_AREA, uom.UOM_LINEAR_FEET, False), 5)
        self.assertEqual(norm(uom.CALC_AREA, uom.UOM_M, True), 14)
        self.assertEqual(norm(uom.CALC_AREA, uom.UOM_MM2, True), 12)
        # Length and volume families.
        self.assertEqual(norm(uom.CALC_LINEAR_LENGTH, uom.UOM_INCHES, False), 1)
        self.assertEqual(norm(uom.CALC_LINEAR_LENGTH, uom.UOM_SQUARE_FEET, False), 2)
        self.assertEqual(norm(uom.CALC_LINEAR_LENGTH, uom.UOM_INCHES, True), 13)
        self.assertEqual(norm(uom.CALC_VOLUME, uom.UOM_CUBIC_YARDS, False), 9)
        self.assertEqual(norm(uom.CALC_VOLUME, uom.UOM_EACH, False), 8)
        self.assertEqual(norm(uom.CALC_VOLUME, uom.UOM_EACH, True), 16)
        # Counts always use EACH.
        self.assertEqual(norm(uom.CALC_COUNT, uom.UOM_LINEAR_FEET, False), 0)
        self.assertEqual(norm(uom.CALC_COUNT, uom.UOM_M, True), 0)

    def test_calculation_normalization_over_tuples_and_conditions(self):
        self.assertEqual(
            uom.normalize_uoms_for_calculations((11, 1, 23), (2, 5, 2), False),
            (5, 2, 0),
        )
        self.assertEqual(uom.normalize_uoms_for_calculations((), (), True), ())
        condition = Condition(
            uid="c",
            calc_type1=uom.CALC_AREA,
            calc_type2=uom.CALC_LINEAR_LENGTH,
            calc_type3=0,
            uom1=uom.UOM_LINEAR_FEET,
            uom2=uom.UOM_SQUARE_FEET,
            uom3=uom.UOM_LINEAR_FEET,
        )
        returned = uom.normalize_condition_uoms_for_system(condition, True)
        self.assertIs(returned, condition)
        self.assertEqual((condition.uom1, condition.uom2, condition.uom3), (14, 13, 13))
        uom.normalize_condition_uoms_for_system(condition, False)
        self.assertEqual((condition.uom1, condition.uom2, condition.uom3), (5, 2, 2))


class UomConversionTests(unittest.TestCase):
    def test_every_unit_divides_inches_by_its_size_in_inches(self):
        expectations = {
            uom.UOM_EACH: 1.0,
            uom.UOM_INCHES: 1.0,
            uom.UOM_LINEAR_FEET: 1 / 12,
            uom.UOM_LINEAR_YARDS: 1 / 36,
            uom.UOM_SQUARE_INCHES: 1.0,
            uom.UOM_SQUARE_FEET: 1 / 144,
            uom.UOM_SQUARE_YARDS: 1 / 1296,
            uom.UOM_SQUARE_ROOFING: 1 / 14400,
            uom.UOM_CUBIC_FEET: 1 / 1728,
            uom.UOM_CUBIC_YARDS: 1 / 46656,
            uom.UOM_MM: 25.4,
            uom.UOM_M: 0.0254,
            uom.UOM_MM2: 25.4 ** 2,
            uom.UOM_M2: 25.4 ** 2 / 1_000_000,
            uom.UOM_MM3: 25.4 ** 3,
            uom.UOM_M3: 25.4 ** 3 / 1_000_000_000,
        }
        for code, per_unit in expectations.items():
            with self.subTest(code=code):
                self.assertAlmostEqual(uom.convert_to_uom(1.0, code) / per_unit, 1.0, places=12)
                self.assertAlmostEqual(
                    uom.convert_to_uom(3456.0, code) / (3456.0 * per_unit), 1.0, places=12
                )
        self.assertEqual(uom.convert_to_uom(5.0, 99), 5.0)
        self.assertEqual(uom.convert_to_uom(0.0, uom.UOM_SQUARE_FEET), 0.0)
        self.assertEqual(uom.convert_to_uom(-144.0, uom.UOM_SQUARE_FEET), -1.0)

    def test_rounding_goes_up_to_the_next_increment_expressed_in_the_same_unit(self):
        convert = uom.convert_and_round_quantity
        # 30 in = 2.5 LF; a 12 in increment is 1 LF.
        self.assertAlmostEqual(convert(30.0, uom.UOM_LINEAR_FEET), 2.5)
        self.assertAlmostEqual(convert(30.0, uom.UOM_LINEAR_FEET, True, 12.0), 3.0)
        self.assertAlmostEqual(convert(24.0, uom.UOM_LINEAR_FEET, True, 12.0), 2.0)
        self.assertAlmostEqual(convert(13.0, uom.UOM_INCHES, True, 12.0), 24.0)
        self.assertAlmostEqual(convert(13.0, uom.UOM_INCHES, True, 0.5), 13.0)
        self.assertAlmostEqual(convert(13.2, uom.UOM_INCHES, True, 0.5), 13.5)

    def test_rounding_is_skipped_without_the_flag_or_with_a_non_positive_increment(self):
        convert = uom.convert_and_round_quantity
        for flag, increment in ((False, 12.0), (True, 0.0), (True, -12.0), (False, 0.0)):
            with self.subTest(flag=flag, increment=increment):
                self.assertAlmostEqual(
                    convert(13.0, uom.UOM_INCHES, flag, increment), 13.0
                )
        self.assertAlmostEqual(convert(13.0, uom.UOM_INCHES, round_up=12.0), 13.0)
        self.assertAlmostEqual(convert(13.5, uom.UOM_INCHES, round_quantity=True), 13.5)


class UomGeometryHelperTests(unittest.TestCase):
    def test_vertices_pair_up_coordinates_and_ignore_a_dangling_value(self):
        self.assertEqual(uom.vertices_from_position([1, 2, 3, 4]), [(1, 2), (3, 4)])
        self.assertEqual(uom.vertices_from_position([1, 2, 3]), [(1, 2)])
        self.assertEqual(uom.vertices_from_position([1]), [])
        self.assertEqual(uom.vertices_from_position([]), [])

    def test_polygon_area_is_absolute_orientation_free_and_needs_three_vertices(self):
        self.assertEqual(uom.calculate_polygon_area([(0, 0), (4, 0), (0, 3)]), 6.0)
        self.assertEqual(uom.calculate_polygon_area([(0, 0), (0, 3), (4, 0)]), 6.0)
        self.assertEqual(uom.calculate_polygon_area([(0, 0), (4, 0)]), 0.0)
        self.assertEqual(uom.calculate_polygon_area([]), 0.0)
        self.assertEqual(
            uom.calculate_polygon_area([(0, 0), (12, 0), (12, 12), (0, 12)]), 144.0
        )
        # A far-away origin must not cost precision: 3 x 4 rectangle at 1e7.
        far = [(1e7, 1e7), (1e7 + 3, 1e7), (1e7 + 3, 1e7 + 4), (1e7, 1e7 + 4)]
        self.assertAlmostEqual(uom.calculate_polygon_area(far), 12.0, places=6)
        self.assertEqual(
            uom.calculate_polygon_area([(0, 0), (4, 0), (4, 0), (0, 3)]), 6.0
        )

    def test_net_area_subtracts_holes_clamps_at_zero_and_reports_square_feet(self):
        self.assertAlmostEqual(uom.calculate_net_area_sf(SQUARE_12), 1.0)
        self.assertAlmostEqual(uom.calculate_net_area_sf(SQUARE_12, [HOLE_6]), 108 / 144)
        self.assertAlmostEqual(
            uom.calculate_net_area_sf(SQUARE_12, [HOLE_6, HOLE_6]), 72 / 144
        )
        self.assertEqual(uom.calculate_net_area_sf(HOLE_6, [SQUARE_12]), 0.0)
        self.assertEqual(uom.calculate_net_area_sf(SQUARE_12, []), 1.0)
        self.assertEqual(uom.calculate_net_area_sf([], None), 0.0)
        self.assertEqual(uom.calculate_net_area_sf([0, 0, 1, 1], None), 0.0)

    def test_bounding_box_is_the_vertex_extent(self):
        self.assertEqual(uom.calculate_bounding_box_inches([]), (0.0, 0.0))
        self.assertEqual(uom.calculate_bounding_box_inches([3, 4]), (0, 0))
        self.assertEqual(uom.calculate_bounding_box_inches([1, 2, 5, 9, -1, 4]), (6, 7))

    def test_perimeter_closes_the_polygon_and_needs_two_vertices(self):
        self.assertEqual(uom._calc_polygon_perimeter(SQUARE_12), 48.0)
        self.assertEqual(uom._calc_polygon_perimeter([0, 0, 3, 4]), 10.0)
        self.assertEqual(uom._calc_polygon_perimeter([0, 0]), 0.0)
        self.assertEqual(uom._calc_polygon_perimeter([]), 0.0)
        self.assertEqual(uom._calc_polygon_area_sq_inches([0, 0, 4, 0]), 0.0)

    def test_slope_factor_is_the_hypotenuse_over_run_and_ignores_flat_or_unset_slopes(self):
        self.assertEqual(uom._calc_slope_factor(3, 4), 1.25)
        self.assertEqual(uom._calc_slope_factor(0, 4), 1.0)
        self.assertEqual(uom._calc_slope_factor(3, 0), 1.0)
        self.assertEqual(uom._calc_slope_factor(-3, 4), 1.0)
        self.assertEqual(uom._calc_slope_factor(3, -4), 1.0)
        self.assertEqual(uom._calc_slope_factor(-3, -4), 1.0)
        self.assertEqual(uom._calc_slope_factor(-3, 4, use_absolute=True), 1.25)
        self.assertEqual(uom._calc_slope_factor(3, -4, use_absolute=True), 1.25)
        self.assertEqual(uom._calc_slope_factor(-3, -4, use_absolute=True), 1.25)
        self.assertEqual(uom._calc_slope_factor(0, 0, use_absolute=True), 1.0)


class UomCountQuantityTests(unittest.TestCase):
    def test_every_count_calculation_uses_the_condition_dimensions(self):
        dims = dict(width=3.0, height=7.0, depth=5.0)
        table = {
            0: 0.0,
            uom.CALC_COUNT: 1.0,
            uom.CALC_HEIGHT_OR_LENGTH: 7.0,
            13: 16.0,
            uom.CALC_TOP_BOTTOM: 15.0,
            uom.CALC_TOP_AND_BOTTOM: 30.0,
            uom.CALC_VOLUME: 105.0,
            uom.CALC_WIDTH_SIDE: 21.0,
            uom.CALC_BOTH_WIDTH_SIDES: 42.0,
            uom.CALC_DEPTH_SIDE: 35.0,
            uom.CALC_BOTH_DEPTH_SIDES: 70.0,
            uom.CALC_ALL_SIDES: 112.0,
            uom.CALC_ALL_SIDES_PLUS_TB: 142.0,
            99: 0.0,
        }
        for calc_type, expected in table.items():
            for condition_type in (Condition.TYPE_COUNT, Condition.TYPE_ATTACHMENT):
                with self.subTest(calc_type=calc_type, condition_type=condition_type):
                    self.assertEqual(_quantities(condition_type, calc_type, **dims)[0], expected)

    def test_all_three_quantity_slots_are_computed_independently_with_their_own_units(self):
        result = uom.calculate_condition_quantities(
            Condition.TYPE_COUNT,
            uom.CALC_WIDTH_SIDE,
            uom.CALC_VOLUME,
            uom.CALC_COUNT,
            uom.UOM_SQUARE_FEET,
            uom.UOM_CUBIC_FEET,
            uom.UOM_EACH,
            width=30.0,
            height=12.0,
            depth=6.0,
            thickness=0.0,
        )
        self.assertAlmostEqual(result[0], 30 * 12 / 144)
        self.assertAlmostEqual(result[1], 30 * 6 * 12 / 1728)
        self.assertEqual(result[2], 1.0)
        self.assertNotEqual(result[0], result[1])
        self.assertIsInstance(result, tuple)


class UomLinearQuantityTests(unittest.TestCase):
    def test_every_linear_calculation_uses_length_height_and_thickness(self):
        table = {
            0: 0.0,
            uom.CALC_LINEAR_LENGTH: 5.0,
            2: 1.0,
            3: 35.0,
            uom.CALC_LINEAR_BOTH_SIDES: 70.0,
            5: 10.0,
            6: 20.0,
            7: 14.0,
            uom.CALC_LINEAR_BOTH_ENDS: 28.0,
            9: 90.0,
            20: 70.0,
            99: 0.0,
        }
        for calc_type, expected in table.items():
            with self.subTest(calc_type=calc_type):
                result = _quantities(
                    Condition.TYPE_LINEAR,
                    calc_type,
                    position=[0, 0, 3, 4],
                    height=7.0,
                    thickness=2.0,
                )
                self.assertEqual(result[0], expected)

    def test_segment_lengths_are_summed_every_seven_coordinates(self):
        self.assertEqual(uom._calc_linear_length([0, 0, 3, 4]), 5.0)
        self.assertEqual(uom._calc_linear_length([0, 0, 3, 4, 9, 9, 9, 10, 10, 13, 14]), 10.0)
        self.assertEqual(uom._calc_linear_length([0, 0, 3, 4, 9, 9, 9, 10, 10, 13]), 5.0)
        self.assertEqual(uom._calc_linear_length([0, 0, 3]), 0.0)
        self.assertEqual(uom._calc_linear_length([]), 0.0)
        self.assertEqual(uom._calc_linear_length([0, 0, 3, 4, 1, 2], curve=-1), 5.0)

    def test_slope_scales_linear_length_but_negative_rise_is_not_a_slope(self):
        base = dict(position=[0, 0, 12, 0], rise=3, run=4)
        self.assertEqual(_quantities(Condition.TYPE_LINEAR, 1, **base)[0], 15.0)
        flat = dict(position=[0, 0, 12, 0], rise=-3, run=4)
        self.assertEqual(_quantities(Condition.TYPE_LINEAR, 1, **flat)[0], 12.0)

    def test_linear_quantity_converts_to_the_requested_unit(self):
        feet = _quantities(Condition.TYPE_LINEAR, 1, uom.UOM_LINEAR_FEET, position=[0, 0, 24, 0])
        self.assertAlmostEqual(feet[0], 2.0)
        metres = _quantities(Condition.TYPE_LINEAR, 1, uom.UOM_M, position=[0, 0, 100, 0])
        self.assertAlmostEqual(metres[0], 2.54)

    def test_a_missing_position_yields_zero(self):
        for position in (None, [], [1.0]):
            self.assertEqual(
                _quantities(Condition.TYPE_LINEAR, 1, position=position)[0], 0.0
            )

    def test_a_curve_through_three_collinear_points_measures_the_straight_distance(self):
        length = uom._calc_linear_length([0, 0, 100, 0, 50, 0], curve=0)
        self.assertAlmostEqual(length, 100.0, places=6)
        vertical = uom._calc_linear_length([0, 0, 0, 100, 0, 50], curve=0)
        self.assertAlmostEqual(vertical, 100.0, places=6)

    def test_a_curve_through_three_points_of_a_circle_measures_the_arc(self):
        radius = 100.0
        quarter = [
            radius, 0.0,
            0.0, radius,
            radius * math.cos(math.pi / 4), radius * math.sin(math.pi / 4),
        ]
        self.assertAlmostEqual(
            uom._calc_linear_length(quarter, curve=0), radius * math.pi / 2, delta=0.05
        )
        # Reversed travel direction measures the same arc.
        reversed_quarter = [0.0, radius, radius, 0.0, *quarter[4:]]
        self.assertAlmostEqual(
            uom._calc_linear_length(reversed_quarter, curve=0), radius * math.pi / 2, delta=0.05
        )
        # Half circle through the top point.
        half = [radius, 0.0, -radius, 0.0, 0.0, radius]
        self.assertAlmostEqual(
            uom._calc_linear_length(half, curve=0), radius * math.pi, delta=0.1
        )
        lower_half = [radius, 0.0, -radius, 0.0, 0.0, -radius]
        self.assertAlmostEqual(
            uom._calc_linear_length(lower_half, curve=0), radius * math.pi, delta=0.1
        )

    def test_a_seventh_value_places_the_arc_by_signed_offset_from_the_chord(self):
        semicircle = uom._calc_linear_length([0, 0, 100, 0, 0, 0, -50], curve=0)
        self.assertAlmostEqual(semicircle, 50 * math.pi, delta=0.1)
        mirrored = uom._calc_linear_length([0, 0, 100, 0, 0, 0, 50], curve=0)
        self.assertAlmostEqual(mirrored, 50 * math.pi, delta=0.1)
        zero_offset = uom._calc_linear_length([0, 0, 100, 0, 0, 0, 0], curve=0)
        self.assertAlmostEqual(zero_offset, 100.0, places=6)
        degenerate = uom._calc_linear_length([5, 5, 5, 5, 5, 5, 20], curve=0)
        self.assertAlmostEqual(degenerate, 0.0, places=9)

    def test_curve_needs_a_control_point_and_a_non_negative_curve_flag(self):
        straight = uom._calc_linear_length([0, 0, 100, 0, 50, 40], curve=-1)
        self.assertEqual(straight, 100.0)
        too_short = uom._calc_linear_length([0, 0, 100, 0, 50], curve=0)
        self.assertEqual(too_short, 100.0)
        bent = uom._calc_linear_length([0, 0, 100, 0, 50, 40], curve=0)
        self.assertGreater(bent, 100.0)
        enabled = uom._calc_linear_length([0, 0, 100, 0, 50, 40], curve=3)
        self.assertEqual(enabled, bent)

    def test_curve_helpers_agree_with_closed_forms(self):
        self.assertEqual(uom._perp_slope(1.0, 0.0), math.inf)
        self.assertEqual(uom._perp_slope(0.0, 1.0), 0.0)
        self.assertEqual(uom._perp_slope(0.0, 0.0), math.inf)
        self.assertEqual(uom._perp_slope(2.0, 4.0), -0.5)
        self.assertEqual(uom._perp_slope(1.0, 2.0), -0.5)
        self.assertEqual(uom._perp_slope(-2.0, 4.0), 0.5)
        points = uom._quadratic_curve_points(0, 0, 10, 0, 5, 10, 2)
        self.assertEqual(points, [(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)])
        self.assertEqual(
            uom._process_curved_position([1, 2, 3, 4, 5, 6]), (1, 2, 3, 4, 5, 6)
        )
        x1, y1, x2, y2, cx, cy = uom._process_curved_position([0, 0, 10, 0, 99, 99, -4])
        self.assertEqual((x1, y1, x2, y2), (0, 0, 10, 0))
        self.assertAlmostEqual(cx, 5.0)
        self.assertAlmostEqual(cy, 4.0)
        same = uom._process_curved_position([2, 2, 2, 2, 7, 8, -4])
        self.assertEqual(same, (2, 2, 2, 2, 7, 8))
        self.assertEqual(uom._calc_curve_segments(0, 0, 10, 0, 5, 0), 6)
        self.assertEqual(uom._calc_curve_segments(0, 0, 1000, 0, 500, 0), 64)
        self.assertEqual(uom._calc_curve_segments(0, 0, 100, 0, 50, 0), 20)
        self.assertEqual(uom._calc_curve_segments(0, 0, 100, 0, 50, 50), 32)
        self.assertEqual(uom._calc_curve_segments(5, 5, 5, 5, 5, 5), 6)
        self.assertEqual(uom._calc_curve_segments(5, 5, 5, 5, 5, 105), 32)


class UomAreaQuantityTests(unittest.TestCase):
    def area(self, calc_type, uom_code=0, **kwargs):
        values = dict(
            position=SQUARE_12,
            hole_positions=[HOLE_6],
            thickness=2.0,
            attachment_footprint=10.0,
            attachment_perimeter=14.0,
            grid_size1=3.0,
            grid_size2=4.0,
            gap=1.0,
        )
        values.update(kwargs)
        return _quantities(Condition.TYPE_AREA, calc_type, uom_code, **values)[0]

    def test_every_area_calculation_combines_polygon_holes_attachments_and_grid(self):
        table = {
            0: 0.0,
            uom.CALC_AREA: 108.0,
            12: 98.0,
            14: 48.0,
            uom.CALC_AREA_PERIMETER: 72.0,
            16: 72.0,
            17: 5.4,
            18: 6.0,
            19: 1.0,
            uom.CALC_AREA_VOLUME: 216.0,
            22: 196.0,
            23: 1.0,
            33: 86.0,
            34: 144.0,
            35: 288.0,
            99: 0.0,
        }
        for calc_type, expected in table.items():
            with self.subTest(calc_type=calc_type):
                self.assertAlmostEqual(self.area(calc_type), expected)

    def test_grid_calculations_return_zero_when_a_cell_has_no_positive_size(self):
        for calc_type in (16, 17, 18):
            for overrides in (
                dict(grid_size1=0.0, grid_size2=0.0, gap=0.0),
                dict(grid_size1=-1.0, gap=1.0),
                dict(grid_size2=-1.0, gap=1.0),
                dict(grid_size1=0.0, gap=0.0),
            ):
                with self.subTest(calc_type=calc_type, overrides=overrides):
                    self.assertEqual(self.area(calc_type, **overrides), 0.0)

    def test_grid_gap_adds_to_each_cell_size(self):
        self.assertAlmostEqual(self.area(16, grid_size1=5.0, grid_size2=2.0, gap=1.0), 2 * 12 + 4 * 12)
        self.assertAlmostEqual(self.area(18, grid_size1=5.0, grid_size2=2.0, gap=1.0), 2 * 4)
        self.assertAlmostEqual(self.area(17, grid_size1=5.0, grid_size2=2.0, gap=1.0), 108 / 18)

    def test_holes_accumulate_and_are_optional(self):
        self.assertAlmostEqual(self.area(uom.CALC_AREA, hole_positions=None), 144.0)
        self.assertAlmostEqual(self.area(uom.CALC_AREA, hole_positions=[]), 144.0)
        self.assertAlmostEqual(self.area(uom.CALC_AREA, hole_positions=[HOLE_6, HOLE_6]), 72.0)
        self.assertAlmostEqual(self.area(uom.CALC_AREA_PERIMETER, hole_positions=[HOLE_6, HOLE_6]), 96.0)

    def test_slope_scales_area_perimeter_and_hole_measures_and_uses_magnitudes(self):
        self.assertAlmostEqual(self.area(uom.CALC_AREA, rise=3, run=4), 108 * 1.25)
        self.assertAlmostEqual(self.area(uom.CALC_AREA, rise=-3, run=-4), 108 * 1.25)
        self.assertAlmostEqual(self.area(14, rise=3, run=4), 48 * 1.25)
        self.assertAlmostEqual(self.area(uom.CALC_AREA_PERIMETER, rise=3, run=4), 72 * 1.25)
        self.assertAlmostEqual(self.area(34, rise=3, run=4), 144 * 1.25)
        # The bounding box (grid counts) is not slope scaled.
        self.assertAlmostEqual(self.area(18, rise=3, run=4), 6.0)

    def test_area_converts_to_the_requested_unit_and_rounds_up(self):
        self.assertAlmostEqual(self.area(uom.CALC_AREA, uom.UOM_SQUARE_FEET), 108 / 144)
        self.assertAlmostEqual(self.area(uom.CALC_AREA, uom.UOM_SQUARE_YARDS), 108 / 1296)
        rounded = self.area(
            uom.CALC_AREA, uom.UOM_SQUARE_FEET, round_quantity=True, round_up=144.0
        )
        self.assertAlmostEqual(rounded, 1.0)

    def test_a_missing_or_degenerate_polygon_yields_zero_area_but_keeps_a_two_point_perimeter(self):
        for position in (None, [], [0, 0, 1, 1]):
            with self.subTest(position=position):
                self.assertEqual(
                    self.area(uom.CALC_AREA, position=position, hole_positions=None), 0.0
                )
        self.assertEqual(self.area(14, position=None, hole_positions=None), 0.0)
        self.assertAlmostEqual(
            self.area(14, position=[0, 0, 1, 1], hole_positions=None), 2 * 2 ** 0.5
        )


def _arc_length(radius, start_deg, through_deg, end_deg):
    """Arc from start to end that passes through the middle angle (independent oracle)."""
    full = 360.0
    ccw_to_end = (end_deg - start_deg) % full
    ccw_to_through = (through_deg - start_deg) % full
    sweep = ccw_to_end if ccw_to_through <= ccw_to_end else full - ccw_to_end
    return radius * math.radians(sweep)


class UomCurvedArcTests(unittest.TestCase):
    def circle_point(self, radius, degrees):
        angle = math.radians(degrees)
        return radius * math.cos(angle), radius * math.sin(angle)

    def test_arc_length_matches_the_circle_for_the_listed_orientations_and_chord_directions(self):
        # Not "every" orientation: arcs whose control point lies close to one end of an
        # arc longer than 180 degrees are measured on the wrong side by production
        # (see UomArcKnownLimitationTests, an owner decision).
        radius = 100.0
        cases = (
            (0, 45, 90),
            (90, 45, 0),
            (0, 90, 180),
            (180, 90, 0),
            (180, 270, 0),
            (0, 270, 180),
            (30, 120, 250),
            (250, 120, 30),
            (135, 45, 270),
            (270, 135, 45),
            (45, 315, 135),
            (45, 135, 225),
            (10, 20, 30),
            (200, 100, 20),
        )
        for start, through, end in cases:
            with self.subTest(arc=(start, through, end)):
                p1 = self.circle_point(radius, start)
                p2 = self.circle_point(radius, end)
                c = self.circle_point(radius, through)
                position = [*p1, *p2, *c]
                expected = _arc_length(radius, start, through, end)
                self.assertAlmostEqual(
                    uom._calc_linear_length(position, curve=0), expected, delta=expected * 0.004
                )

    def test_arcs_with_axis_aligned_chord_segments_use_the_dedicated_center_formulas(self):
        radius = 100.0
        s = radius * math.sqrt(0.5)
        # first segment horizontal, second segment horizontal, vertical segments
        for p1, c, p2, start, through, end in (
            ((-s, s), (s, s), (0.0, -radius), 135, 45, 270),
            ((0.0, -radius), (-s, s), (s, s), 270, 135, 45),
            ((s, s), (s, -s), (-s, -s), 45, 315, 225),
            ((-s, -s), (s, -s), (s, s), 225, 315, 45),
        ):
            with self.subTest(arc=(start, through, end)):
                expected = _arc_length(radius, start, through, end)
                self.assertAlmostEqual(
                    uom._calc_linear_length([*p1, *p2, *c], curve=0),
                    expected,
                    delta=expected * 0.004,
                )

    def test_a_seventh_value_also_works_for_tilted_chords_and_short_chords(self):
        x1, y1, x2, y2, cx, cy = uom._process_curved_position([1, 2, 7, 10, 0, 0, 5])
        self.assertEqual((x1, y1, x2, y2), (1, 2, 7, 10))
        self.assertAlmostEqual(cx, 8.0)
        self.assertAlmostEqual(cy, 3.0)
        cx, cy = uom._process_curved_position([0, 0, 0, 10, 99, 99, -4])[4:]
        self.assertAlmostEqual(cx, -4.0)
        self.assertAlmostEqual(cy, 5.0)
        cx, cy = uom._process_curved_position([0, 0, 0.5, 0, 99, 99, -2])[4:]
        self.assertAlmostEqual(cx, 0.25)
        self.assertAlmostEqual(cy, 2.0)

    def test_segment_count_adds_the_control_point_offset_from_the_chord_clamped_to_the_chord(self):
        self.assertEqual(uom._calc_curve_segments(0, 0, 60, 80, 10, 50), 24)
        self.assertEqual(uom._calc_curve_segments(0, 0, 100, 0, 150, 30), 44)
        self.assertEqual(uom._calc_curve_segments(0, 0, 100, 0, -50, 30), 44)
        self.assertEqual(uom._calc_curve_segments(0, 0, 100, 0, 50, 30), 26)
        self.assertEqual(uom._calc_curve_segments(0, 0, 100, 0, 50, 5), 21)
        self.assertEqual(uom._calc_curve_segments(0, 0, 100, 0, 50, 4.9), 20)

    def test_collinear_control_points_fall_back_to_the_quadratic_and_measure_its_path(self):
        # Control point beyond the end: the quadratic overshoots to 112.5 and returns.
        horizontal = uom._calc_linear_length([0, 0, 100, 0, 150, 0], curve=0)
        self.assertAlmostEqual(horizontal, 125.0, delta=0.1)
        vertical = uom._calc_linear_length([0, 0, 0, 100, 0, 150], curve=0)
        self.assertAlmostEqual(vertical, 125.0, delta=0.1)
        diagonal = uom._calc_linear_length([0, 0, 60, 80, 90, 120], curve=0)
        self.assertAlmostEqual(diagonal, 125.0, delta=0.1)

    def test_an_off_chord_control_point_measures_the_circle_through_all_three_points(self):
        # (0,0), (50,40), (100,0) lie on a circle of radius 51.25 centred 11.25 below the chord.
        radius = 51.25
        sweep = 2 * math.atan2(50.0, 11.25)
        self.assertAlmostEqual(
            uom._calc_linear_length([0, 0, 100, 0, 50, 40], curve=0), radius * sweep, delta=0.3
        )


class UomDefaultArgumentTests(unittest.TestCase):
    def test_optional_inputs_default_to_no_slope_no_holes_no_attachments_and_no_rounding(self):
        square = [0, 0, 12, 0, 12, 12, 0, 12]
        for calc_type, expected in (
            (uom.CALC_AREA, 144.0),
            (12, 144.0),
            (14, 48.0),
            (uom.CALC_AREA_PERIMETER, 48.0),
            (33, 48.0),
            (16, 0.0),
            (17, 0.0),
            (18, 0.0),
            (uom.CALC_AREA_VOLUME, 0.0),
        ):
            with self.subTest(calc_type=calc_type):
                result = uom.calculate_condition_quantities(
                    Condition.TYPE_AREA,
                    calc_type,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    square,
                )
                self.assertEqual(result, (expected, 0.0, 0.0))

    def test_default_curve_is_a_straight_polyline_and_default_rounding_is_off(self):
        result = uom.calculate_condition_quantities(
            Condition.TYPE_LINEAR, 1, 0, 0, 1, 0, 0, 0.0, 0.0, 0.0, 0.0, [0, 0, 100, 0, 50, 40]
        )
        self.assertEqual(result, (100.0, 0.0, 0.0))
        rounded_by_default = uom.calculate_condition_quantities(
            Condition.TYPE_LINEAR, 1, 0, 0, 1, 0, 0, 0.0, 0.0, 0.0, 0.0, [0, 0, 13.5, 0]
        )
        self.assertEqual(rounded_by_default[0], 13.5)

    def test_unit_size_and_sub_unit_grid_cells_are_valid_cells(self):
        base = dict(position=[0, 0, 12, 0, 12, 12, 0, 12], hole_positions=None)
        one = _quantities(Condition.TYPE_AREA, 17, grid_size1=0.5, grid_size2=0.5, gap=0.5, **base)
        self.assertAlmostEqual(one[0], 144.0)
        half = _quantities(Condition.TYPE_AREA, 17, grid_size1=0.25, grid_size2=0.25, gap=0.25, **base)
        self.assertAlmostEqual(half[0], 144.0 / 0.25)
        small = _quantities(Condition.TYPE_AREA, 16, grid_size1=0.5, grid_size2=0.5, gap=0.0, **base)
        self.assertAlmostEqual(small[0], 24 * 12 + 24 * 12)
        tiles = _quantities(Condition.TYPE_AREA, 18, grid_size1=0.5, grid_size2=0.5, gap=0.0, **base)
        self.assertAlmostEqual(tiles[0], 24 * 24)

    def test_slope_factor_with_fractional_rise_and_run(self):
        self.assertAlmostEqual(uom._calc_slope_factor(0.5, 0.5), math.sqrt(2.0))
        self.assertAlmostEqual(uom._calc_slope_factor(0.3, 0.4), 1.25)
        self.assertEqual(uom._calc_slope_factor(0.0, 0.5), 1.0)
        self.assertAlmostEqual(uom._calc_slope_factor(0.5, 0.0), 1.0)

    def test_triangle_polygon_has_area_and_helper_handles_exactly_three_vertices(self):
        self.assertEqual(uom._calc_polygon_area_sq_inches([0, 0, 4, 0, 0, 3]), 6.0)
        result = _quantities(
            Condition.TYPE_AREA, uom.CALC_AREA, position=[0, 0, 4, 0, 0, 3], hole_positions=None
        )
        self.assertEqual(result[0], 6.0)


class UomTranslatedArcTests(unittest.TestCase):
    CENTERS = ((0.0, 0.0), (300.0, -200.0), (-1234.5, 777.25))
    CASES = (
        (0, 45, 90),
        (90, 45, 0),
        (0, 90, 180),
        (180, 270, 0),
        (30, 120, 250),
        (250, 120, 30),
        (135, 45, 270),
        (270, 135, 45),
        (45, 315, 135),
        (10, 20, 30),
        (200, 100, 20),
    )

    def points(self, center, radius, start, through, end):
        def at(degrees):
            angle = math.radians(degrees)
            return (
                center[0] + radius * math.cos(angle),
                center[1] + radius * math.sin(angle),
            )

        return at(start), at(through), at(end)

    def test_arc_lengths_do_not_depend_on_where_the_circle_is(self):
        radius = 100.0
        for center in self.CENTERS:
            for start, through, end in self.CASES:
                with self.subTest(center=center, arc=(start, through, end)):
                    p1, c, p2 = self.points(center, radius, start, through, end)
                    expected = _arc_length(radius, start, through, end)
                    self.assertAlmostEqual(
                        uom._calc_linear_length([*p1, *p2, *c], curve=0),
                        expected,
                        delta=expected * 0.004,
                    )

    def test_arc_points_start_and_end_on_the_chord_ends_pass_the_control_point_and_stay_on_the_circle(self):
        radius = 100.0
        for center in self.CENTERS:
            for start, through, end in self.CASES:
                with self.subTest(center=center, arc=(start, through, end)):
                    p1, c, p2 = self.points(center, radius, start, through, end)
                    segments = uom._calc_curve_segments(*p1, *p2, *c)
                    points = uom._advanced_curve_points(*p1, *p2, *c, segments)
                    self.assertEqual(len(points), segments + 1)
                    self.assertAlmostEqual(points[0][0], p1[0], delta=1e-6)
                    self.assertAlmostEqual(points[0][1], p1[1], delta=1e-6)
                    self.assertAlmostEqual(points[-1][0], p2[0], delta=1e-6)
                    self.assertAlmostEqual(points[-1][1], p2[1], delta=1e-6)
                    for x, y in points:
                        self.assertAlmostEqual(math.hypot(x - center[0], y - center[1]), radius, delta=1e-6)
                    sweep = _arc_length(radius, start, through, end) / radius
                    step = radius * sweep / segments
                    nearest = min(math.hypot(x - c[0], y - c[1]) for x, y in points)
                    self.assertLessEqual(nearest, step)

    def test_translating_a_curve_does_not_change_its_segment_count(self):
        for case in (
            (0, 0, 60, 80, 10, 50),
            (0, 0, 100, 0, 150, 30),
            (0, 0, 100, 0, -50, 30),
            (0, 0, 100, 0, 50, 30),
            (0, 0, 100, 0, 150, 0),
            (0, 0, 0.5, 0, 0.25, 50),
            (0, 0, 1000, 0, 500, 500),
            (0, 0, 30, 40, 30, 0),
            (0, 0, 120, 50, 20, 90),
        ):
            base = uom._calc_curve_segments(*case)
            for dx, dy in ((1000.0, -500.0), (-37.5, 12.25)):
                shifted = (
                    case[0] + dx, case[1] + dy, case[2] + dx,
                    case[3] + dy, case[4] + dx, case[5] + dy,
                )
                with self.subTest(case=case, shift=(dx, dy)):
                    self.assertEqual(uom._calc_curve_segments(*shifted), base)

    def test_short_chords_still_add_the_control_point_offset_and_the_total_is_capped(self):
        self.assertEqual(uom._calc_curve_segments(0, 0, 0.5, 0, 0.25, 50), 26)
        self.assertEqual(uom._calc_curve_segments(0, 0, 1000, 0, 500, 500), 64)
        self.assertEqual(uom._calc_curve_segments(0, 0, 100, 0, 50, 1000), 64)
        self.assertEqual(uom._calc_curve_segments(0, 0, 30, 40, 30, 0), 15)
        self.assertEqual(uom._calc_curve_segments(0, 0, 120, 50, 20, 90), 46)

    def test_collinear_curves_are_unaffected_by_translation(self):
        for dx, dy in ((0.0, 0.0), (500.0, 300.0), (-77.0, 123.0)):
            horizontal = uom._calc_linear_length([dx, dy, 100 + dx, dy, 150 + dx, dy], curve=0)
            self.assertAlmostEqual(horizontal, 125.0, delta=0.1)
            diagonal = uom._calc_linear_length(
                [dx, dy, 60 + dx, 80 + dy, 90 + dx, 120 + dy], curve=0
            )
            self.assertAlmostEqual(diagonal, 125.0, delta=0.1)


class UomRawAreaDefaultTests(unittest.TestCase):
    def test_grid_calculations_called_without_grid_arguments_find_no_cells(self):
        for calc_type in (16, 17, 18):
            with self.subTest(calc_type=calc_type):
                self.assertEqual(
                    uom._calc_raw_for_area(calc_type, 2.0, 144.0, 0.0, 48.0, 0.0, 0.0, 0.0),
                    0.0,
                )
        self.assertEqual(
            uom._calc_raw_for_area(uom.CALC_AREA, 2.0, 144.0, 36.0, 48.0, 24.0, 0.0, 0.0),
            108.0,
        )


class UomSecondReviewGapTests(unittest.TestCase):
    """Cases that need inputs the first tests never used (non-divisible, asymmetric,
    one-sided or numerically degenerate), found by the independent verifier."""

    SQUARE = [0, 0, 12, 0, 12, 12, 0, 12]

    @staticmethod
    def quantity(condition_type, calc_type, uom_code=0, **kwargs):
        values = dict(
            condition_type=condition_type,
            calc_type1=calc_type,
            calc_type2=0,
            calc_type3=0,
            uom1=uom_code,
            uom2=0,
            uom3=0,
            width=0.0,
            height=0.0,
            depth=0.0,
            thickness=0.0,
        )
        values.update(kwargs)
        return uom.calculate_condition_quantities(**values)

    def test_linear_length_reads_each_segment_from_its_own_start_point(self):
        # Segments that do not start at the origin or on the diagonal: a swapped
        # coordinate index would measure a different length.
        self.assertEqual(uom._calc_linear_length([1, 2, 4, 6]), 5.0)
        self.assertEqual(
            uom._calc_linear_length([1, 2, 4, 6, 0, 0, 0, 20, 30, 23, 34]), 10.0
        )

    def test_a_triangle_with_an_odd_doubled_area_has_a_half_unit_area(self):
        self.assertEqual(uom.calculate_polygon_area([(0, 0), (1, 0), (0, 1)]), 0.5)
        self.assertEqual(uom.calculate_polygon_area([(0, 0), (0, 1), (1, 0)]), 0.5)

    def test_grid_calculations_round_cell_counts_over_non_divisible_boxes(self):
        # unit = grid size + gap = 5; a 12 x 12 inch box needs ceil(12/5) = 3 cells for
        # the length formula and floor(12/5) = 2 whole cells per axis for the tile count.
        def raw(calc_type, size1, size2, gap):
            return uom._calc_raw_for_area(
                calc_type, 0.0, 144.0, 0.0, 48.0, 0.0, 0.0, 0.0, size1, size2, gap, 12.0, 12.0
            )

        self.assertEqual(raw(16, 4.0, 4.0, 1.0), 3 * 12 + 3 * 12)
        self.assertEqual(raw(16, 4.0, 3.0, 0.0), 3 * 12 + 4 * 12)
        self.assertEqual(raw(18, 4.0, 4.0, 1.0), 2 * 2)
        self.assertAlmostEqual(raw(17, 4.0, 4.0, 1.0), 144.0 / 25.0)

    def test_a_negative_cell_size_is_not_a_cell(self):
        for calc_type in (16, 17, 18):
            for size1, size2 in ((-5.0, 2.0), (2.0, -5.0)):
                with self.subTest(calc_type=calc_type, sizes=(size1, size2)):
                    self.assertEqual(
                        uom._calc_raw_for_area(
                            calc_type, 0.0, 144.0, 0.0, 48.0, 0.0, 0.0, 0.0,
                            size1, size2, 1.0, 12.0, 12.0,
                        ),
                        0.0,
                    )

    def test_both_grid_sizes_are_needed_to_find_cells(self):
        for calc_type in (16, 17, 18):
            for only in ({"grid_size1": 3.0}, {"grid_size2": 3.0}):
                with self.subTest(calc_type=calc_type, only=only):
                    self.assertEqual(
                        uom._calc_raw_for_area(
                            calc_type, 0.0, 144.0, 0.0, 48.0, 0.0, 0.0, 0.0, **only
                        ),
                        0.0,
                    )
                    self.assertEqual(
                        self.quantity(
                            Condition.TYPE_AREA, calc_type, position=self.SQUARE, **only
                        )[0],
                        0.0,
                    )

    def test_a_slope_needs_both_rise_and_run(self):
        self.assertEqual(
            self.quantity(Condition.TYPE_AREA, 11, position=self.SQUARE, run=4.0)[0], 144.0
        )
        self.assertEqual(
            self.quantity(Condition.TYPE_AREA, 11, position=self.SQUARE, rise=3.0)[0], 144.0
        )
        for only in ({"run": 4.0}, {"rise": 3.0}):
            self.assertEqual(
                self.quantity(
                    Condition.TYPE_LINEAR, 1, position=[0, 0, 12, 0], **only
                )[0],
                12.0,
            )

    def test_rounding_needs_an_increment_as_well_as_the_flag(self):
        result = self.quantity(
            Condition.TYPE_LINEAR, 1, 1, position=[0, 0, 13.5, 0], round_quantity=True
        )
        self.assertEqual(result[0], 13.5)

    def test_a_curve_with_a_control_offset_uses_more_than_the_minimum_segments(self):
        # 6 segments is the floor for a straight chord; the offset adds one here.
        self.assertEqual(uom._calc_curve_segments(0, 0, 10, 0, 5, 0), 6)
        self.assertEqual(uom._calc_curve_segments(0, 0, 10, 0, 5, 5), 7)

    def test_only_the_first_seven_values_describe_a_curved_segment(self):
        # chord (0,0)-(100,0), 7th value -50: a semicircle of radius 50 whose length is
        # 50 pi; the trailing values belong to the next segment and are ignored.
        length = uom._calc_linear_length([0, 0, 100, 0, 0, 0, -50, 1, 1, 2, 2], curve=0)
        self.assertAlmostEqual(length, 50 * math.pi, delta=0.1)

    def test_coincident_end_points_with_a_far_control_point_measure_the_out_and_back_path(self):
        # Start and end are the same point (-5, 0); the quadratic through a control at
        # (5, 0) goes out to x = 0 and back: 5 + 5.
        self.assertAlmostEqual(
            uom._calc_linear_length([-5, 0, -5, 0, 5, 0], curve=0), 10.0, delta=0.5
        )

    def test_numerically_degenerate_circles_fall_back_to_the_quadratic_path(self):
        # Three points that are collinear to within floating point error define a
        # circle with a meaningless huge radius; the length must stay near the chord.
        triples = (
            (-15.05766633024992, 102.25967331254812, 27072.542757617703,
             -2214.0656632762107, 20067.03261395505, -1615.0077775681077),
            (3.2626032666664124, 369.36683081795644, -70452.7258311968,
             -30699.856722606186, -15689.96504820314, -6550.930634790724),
            (-179.919479464134, 60.15739467281006, 54892.68210123489,
             7084.611892722189, 20583.415063180953, 2708.4996654084894),
        )
        for triple in triples:
            with self.subTest(triple=triple):
                chord = math.hypot(triple[2] - triple[0], triple[3] - triple[1])
                self.assertAlmostEqual(
                    uom._calc_linear_length(list(triple), curve=0), chord, places=3
                )


class UomArcKnownLimitationTests(unittest.TestCase):
    """Documented defect, OWNER DECISION: the arc side is chosen with
    clockwise = (cross1 + cross2) < 0 (uom_service._advanced_curve_points and the
    same expression in cpp_extensions/src/linear_geom/linear_geom.cpp). The sum of the
    two partial sines is negative when the control point is close to one end of an
    arc longer than 180 degrees, so the minor arc is measured instead of the arc
    through the control point. These tests state the CORRECT expectation and are
    marked as expected failures until the owner decides whether original OST has
    the same behavior (compatibility) or the formula should be fixed in Python and
    C++ together. When fixed, remove the decorators."""

    @staticmethod
    def measured(start, through, end, radius=100.0):
        def at(degrees):
            angle = math.radians(degrees)
            return radius * math.cos(angle), radius * math.sin(angle)

        position = [*at(start), *at(end), *at(through)]
        return uom._calc_linear_length(position, curve=0), _arc_length(
            radius, start, through, end
        )

    @unittest.expectedFailure
    def test_control_point_close_to_the_end_of_a_major_arc_is_measured_on_the_major_arc(self):
        measured, expected = self.measured(0, 250, 251)
        self.assertAlmostEqual(measured, expected, delta=expected * 0.01)  # ~438.1, got ~190.2

    @unittest.expectedFailure
    def test_control_point_beyond_a_short_chord_is_measured_on_the_arc_through_it(self):
        measured, expected = self.measured(0, 110, 100)
        self.assertAlmostEqual(measured, expected, delta=expected * 0.01)  # ~453.8, got ~174.5

    def test_the_current_production_values_for_those_arcs_are_recorded(self):
        # Pins today's behavior so a deliberate fix is noticed (and the two
        # expected-failure tests above are then switched on).
        measured, _expected = self.measured(0, 250, 251)
        self.assertAlmostEqual(measured, 190.2, delta=0.5)
        measured, _expected = self.measured(0, 110, 100)
        self.assertAlmostEqual(measured, 174.5, delta=0.5)


class UomArcOrientationRegressionTests(unittest.TestCase):
    def test_large_and_small_arcs_with_a_far_origin_are_measured_on_the_arc_through_the_control_point(self):
        for radius, center, start, through, end in (
            (100.0, (6.0, 17.5), 33.1, 235.4, 73.3),
            (100.0, (-431.2, 220.2), 69.8, 343.2, 90.4),
            (100.0, (237.1, -37.4), 332.9, 96.9, 294.2),
            (5.0, (-445.3, -358.3), 61.9, 263.4, 285.0),
        ):
            with self.subTest(arc=(radius, start, through, end)):
                def at(degrees):
                    angle = math.radians(degrees)
                    return (
                        center[0] + radius * math.cos(angle),
                        center[1] + radius * math.sin(angle),
                    )

                position = [*at(start), *at(end), *at(through)]
                expected = _arc_length(radius, start, through, end)
                self.assertAlmostEqual(
                    uom._calc_linear_length(position, curve=0), expected, delta=expected * 0.01 + 0.2
                )
