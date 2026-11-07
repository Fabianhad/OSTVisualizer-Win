import math
import unittest
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.condition_quantity_service import (
    compute_page_quantities,
    compute_takeoff_cubic_yards,
)
from dataclasses import replace
from ost_visualizer.domain.services.uom_service import (
    CALC_AREA,
    CALC_COUNT,
    CALC_DEPTH_SIDE,
    CALC_HEIGHT_OR_LENGTH,
    CALC_WIDTH_SIDE,
    UOM_EACH,
    UOM_LINEAR_FEET,
    UOM_LINEAR_YARDS,
    UOM_SQUARE_FEET,
    UOM_SQUARE_INCHES,
)


class ConditionQuantityServiceConditionBehaviorTests(unittest.TestCase):
    def test_round_quantity_rounds_linear_and_area_results_without_mutating_geometry(
        self,
    ):
        linear = Condition(
            uid="linear",
            condition_type=Condition.TYPE_LINEAR,
            calc_type1=1,
            uom1=1,
            round_quantity=True,
            round_up=12.0,
        )
        area = Condition(
            uid="area",
            condition_type=Condition.TYPE_AREA,
            calc_type1=11,
            uom1=4,
            round_quantity=True,
            round_up=12.0,
        )
        linear_takeoff = Takeoff(
            uid="t1", condition_uid="linear", position=[0.0, 0.0, 13.0, 0.0]
        )
        area_takeoff = Takeoff(
            uid="t2",
            condition_uid="area",
            position=[0.0, 0.0, 13.0, 0.0, 13.0, 13.0, 0.0, 13.0],
        )
        results = compute_page_quantities(
            {"linear": linear, "area": area}, [linear_takeoff, area_takeoff]
        )
        self.assertEqual(results["linear"][0], 24.0)
        self.assertEqual(results["area"][0], 180.0)
        self.assertEqual(linear_takeoff.position, [0.0, 0.0, 13.0, 0.0])
        self.assertEqual(
            area_takeoff.position,
            [0.0, 0.0, 13.0, 0.0, 13.0, 13.0, 0.0, 13.0],
        )

    def test_partial_quantity_request_returns_zero_for_condition_without_takeoffs(self):
        condition = Condition(uid="c1", condition_type=Condition.TYPE_AREA)
        results = compute_page_quantities(
            {"c1": condition}, [], only_condition_uids={"c1"}
        )
        self.assertEqual(results, {"c1": (0.0, 0.0, 0.0)})


class TakeoffLifecycleQuantityTests(unittest.TestCase):
    def setUp(self):
        self.conditions = {
            "area": Condition(
                uid="area",
                condition_type=Condition.TYPE_AREA,
                calc_type1=CALC_AREA,
                uom1=UOM_SQUARE_INCHES,
            ),
            "backout": Condition(
                uid="backout",
                condition_type=Condition.TYPE_AREA,
                calc_type1=CALC_AREA,
                uom1=UOM_SQUARE_INCHES,
            ),
            "attachment": Condition(
                uid="attachment",
                condition_type=Condition.TYPE_ATTACHMENT,
                width=2,
                depth=2,
                calc_type1=CALC_COUNT,
            ),
        }
        self.takeoffs = [
            Takeoff(
                uid="parent",
                condition_uid="area",
                page_uid="page",
                position=[0, 0, 10, 0, 10, 10, 0, 10],
            ),
            Takeoff(
                uid="hole",
                condition_uid="backout",
                page_uid="page",
                parent_uid="parent",
                position=[1, 1, 3, 1, 3, 3, 1, 3],
            ),
            Takeoff(
                uid="point",
                condition_uid="attachment",
                page_uid="page",
                parent_uid="parent",
                position=[5, 5],
            ),
        ]

    def test_attachment_contributes_its_own_quantity(self):
        self.assertEqual(
            compute_page_quantities(self.conditions, self.takeoffs)["attachment"][0], 1
        )

    def test_scoped_area_quantities_include_backout_on_another_condition(self):
        full = compute_page_quantities(self.conditions, self.takeoffs)
        scoped = compute_page_quantities(self.conditions, self.takeoffs, {"area"})
        self.assertEqual(full["area"][0], 96)
        self.assertEqual(scoped, {"area": (96.0, 0.0, 0.0)})

    def test_attachment_aware_area_formula_uses_child_dimensions(self):
        self.conditions["area"] = replace(self.conditions["area"], calc_type1=12)
        self.assertEqual(
            compute_page_quantities(self.conditions, self.takeoffs)["area"][0], 92
        )

    def test_foreign_page_and_missing_condition_children_do_not_subtract_area(self):
        parent, hole, attachment = self.takeoffs
        foreign_hole = replace(hole, page_uid="other-page")
        orphan_attachment = replace(attachment, condition_uid="deleted")
        self.conditions["area"] = replace(self.conditions["area"], calc_type1=12)
        self.assertEqual(
            compute_page_quantities(
                self.conditions, [parent, foreign_hole, orphan_attachment], {"area"}
            ),
            {"area": (100.0, 0.0, 0.0)},
        )
        self.assertEqual(
            compute_page_quantities(self.conditions, self.takeoffs, {"area"}),
            {"area": (92.0, 0.0, 0.0)},
        )


class ConditionQuantityServiceExactTests(unittest.TestCase):
    def area_condition(self, **changes):
        base = dict(
            uid="a",
            condition_type=Condition.TYPE_AREA,
            calc_type1=CALC_AREA,
            uom1=UOM_SQUARE_INCHES,
            calc_type2=CALC_AREA,
            uom2=UOM_SQUARE_INCHES,
            calc_type3=CALC_COUNT,
            uom3=0,
        )
        base.update(changes)
        return Condition(**base)

    def test_all_three_quantities_and_negative_signs_are_accumulated_per_condition(
        self,
    ):
        condition = self.area_condition(calc_type2=14, uom2=UOM_SQUARE_INCHES)
        positive = Takeoff(
            uid="1", condition_uid="a", position=[0, 0, 10, 0, 10, 10, 0, 10]
        )
        negative = Takeoff(
            uid="2",
            condition_uid="a",
            position=[0, 0, 4, 0, 4, 4, 0, 4],
            is_negative=True,
        )
        total = compute_page_quantities({"a": condition}, [positive, negative])["a"]
        self.assertEqual(total, (100.0 - 16.0, 40.0 - 16.0, 1.0 - 1.0))
        only_negative = compute_page_quantities({"a": condition}, [negative])["a"]
        self.assertEqual(only_negative, (-16.0, -16.0, -1.0))

    def test_conditions_are_totaled_separately_and_unknown_conditions_are_skipped(self):
        conditions = {"a": self.area_condition(), "b": self.area_condition(uid="b")}
        takeoffs = [
            Takeoff(uid="1", condition_uid="a", position=[0, 0, 2, 0, 2, 2, 0, 2]),
            Takeoff(uid="2", condition_uid="b", position=[0, 0, 3, 0, 3, 3, 0, 3]),
            Takeoff(uid="3", condition_uid="a", position=[0, 0, 1, 0, 1, 1, 0, 1]),
            Takeoff(uid="4", condition_uid="gone", position=[0, 0, 9, 0, 9, 9, 0, 9]),
        ]
        result = compute_page_quantities(conditions, takeoffs)
        self.assertEqual(sorted(result), ["a", "b"])
        self.assertEqual(result["a"][0], 5.0)
        self.assertEqual(result["b"][0], 9.0)

    def test_only_condition_filter_limits_takeoffs_and_prepopulates_zero_for_known_conditions_only(
        self,
    ):
        conditions = {"a": self.area_condition(), "b": self.area_condition(uid="b")}
        takeoffs = [
            Takeoff(uid="1", condition_uid="a", position=[0, 0, 2, 0, 2, 2, 0, 2]),
            Takeoff(uid="2", condition_uid="b", position=[0, 0, 3, 0, 3, 3, 0, 3]),
        ]
        result = compute_page_quantities(conditions, takeoffs, {"b", "ghost"})
        self.assertEqual(result, {"b": (9.0, 9.0, 1.0)})
        self.assertEqual(compute_page_quantities(conditions, takeoffs, {"ghost"}), {})
        empty_filter = compute_page_quantities(conditions, takeoffs, set())
        self.assertEqual(sorted(empty_filter), ["a", "b"])

    def test_backouts_are_subtracted_only_from_their_parent_and_never_counted_as_primaries(
        self,
    ):
        conditions = {"a": self.area_condition()}
        takeoffs = [
            Takeoff(
                uid="p1",
                condition_uid="a",
                page_uid="pg",
                position=[0, 0, 10, 0, 10, 10, 0, 10],
            ),
            Takeoff(
                uid="p2",
                condition_uid="a",
                page_uid="pg",
                position=[0, 0, 10, 0, 10, 10, 0, 10],
            ),
            Takeoff(
                uid="h",
                condition_uid="a",
                page_uid="pg",
                parent_uid="p1",
                position=[0, 0, 2, 0, 2, 2, 0, 2],
            ),
            Takeoff(
                uid="none-parent",
                condition_uid="a",
                page_uid="pg",
                parent_uid="None",
                position=[0, 0, 1, 0, 1, 1, 0, 1],
            ),
            Takeoff(
                uid="blank-parent",
                condition_uid="a",
                page_uid="pg",
                parent_uid="",
                position=[0, 0, 1, 0, 1, 1, 0, 1],
            ),
        ]
        result = compute_page_quantities(conditions, takeoffs)["a"]
        # p1 (100 - 4) + p2 (100) + two root-like parents of 1 each.
        self.assertEqual(result[0], 96.0 + 100.0 + 1.0 + 1.0)

    def test_non_area_conditions_count_every_takeoff_even_with_a_parent_uid(self):
        conditions = {
            "l": Condition(
                uid="l", condition_type=Condition.TYPE_LINEAR, calc_type1=1, uom1=1
            )
        }
        takeoffs = [
            Takeoff(uid="1", condition_uid="l", position=[0, 0, 5, 0]),
            Takeoff(uid="2", condition_uid="l", parent_uid="1", position=[0, 0, 7, 0]),
        ]
        self.assertEqual(compute_page_quantities(conditions, takeoffs)["l"][0], 12.0)

    def test_attachment_children_subtract_footprint_and_add_perimeter_to_the_parent(
        self,
    ):
        attachment = Condition(
            uid="att",
            condition_type=Condition.TYPE_ATTACHMENT,
            width=2,
            depth=3,
            calc_type1=CALC_COUNT,
        )
        for calc_type, expected in ((12, 100.0 - 6.0), (33, 40.0 + 10.0), (22, 94.0)):
            area = self.area_condition(
                calc_type1=calc_type, uom1=UOM_SQUARE_INCHES, thickness=1.0
            )
            parent = Takeoff(
                uid="p",
                condition_uid="a",
                page_uid="pg",
                position=[0, 0, 10, 0, 10, 10, 0, 10],
            )
            child = Takeoff(
                uid="c",
                condition_uid="att",
                page_uid="pg",
                parent_uid="p",
                position=[5, 5],
            )
            with self.subTest(calc_type=calc_type):
                value = compute_page_quantities(
                    {"a": area, "att": attachment}, [parent, child], {"a"}
                )["a"][0]
                self.assertEqual(value, expected)

    def test_a_child_that_is_neither_area_nor_attachment_does_not_affect_the_parent(
        self,
    ):
        line = Condition(
            uid="l", condition_type=Condition.TYPE_LINEAR, calc_type1=1, uom1=1
        )
        parent = Takeoff(
            uid="p",
            condition_uid="a",
            page_uid="pg",
            position=[0, 0, 10, 0, 10, 10, 0, 10],
        )
        child = Takeoff(
            uid="c",
            condition_uid="l",
            page_uid="pg",
            parent_uid="p",
            position=[0, 0, 5, 5],
        )
        result = compute_page_quantities(
            {"a": self.area_condition(), "l": line}, [parent, child], {"a"}
        )
        self.assertEqual(result["a"][0], 100.0)

    def test_fractional_quantities_are_accumulated_without_integer_truncation(self):
        # 12x9 in = 108 sq in = 0.75 sq ft; the 6x6 in negative is 0.25 sq ft.
        condition = self.area_condition(
            uom1=UOM_SQUARE_FEET,
            uom2=UOM_SQUARE_FEET,
            calc_type3=CALC_AREA,
            uom3=UOM_SQUARE_FEET,
        )
        positive = Takeoff(
            uid="1", condition_uid="a", position=[0, 0, 12, 0, 12, 9, 0, 9]
        )
        negative = Takeoff(
            uid="2",
            condition_uid="a",
            position=[0, 0, 6, 0, 6, 6, 0, 6],
            is_negative=True,
        )
        total = compute_page_quantities({"a": condition}, [positive, negative])["a"]
        self.assertAlmostEqual(total[0], 0.75 - 0.25)
        self.assertAlmostEqual(total[1], 0.75 - 0.25)
        self.assertAlmostEqual(total[2], 0.75 - 0.25)
        only_negative = compute_page_quantities({"a": condition}, [negative])["a"]
        self.assertAlmostEqual(only_negative[0], -0.25)
        self.assertAlmostEqual(only_negative[1], -0.25)
        self.assertAlmostEqual(only_negative[2], -0.25)

    def test_a_child_on_a_different_page_is_ignored_whichever_page_uid_sorts_first(
        self,
    ):
        condition = self.area_condition(uom1=UOM_SQUARE_FEET, uom2=UOM_SQUARE_FEET)
        parent = Takeoff(
            uid="p",
            condition_uid="a",
            page_uid="m-page",
            position=[0, 0, 12, 0, 12, 12, 0, 12],
        )
        for page_uid in ("a-page", "z-page"):
            with self.subTest(child_page=page_uid):
                child = Takeoff(
                    uid="c",
                    condition_uid="a",
                    page_uid=page_uid,
                    parent_uid="p",
                    position=[0, 0, 6, 0, 6, 6, 0, 6],
                )
                total = compute_page_quantities({"a": condition}, [parent, child])["a"]
                self.assertAlmostEqual(total[0], 1.0)
        same_page = Takeoff(
            uid="c",
            condition_uid="a",
            page_uid="m-page",
            parent_uid="p",
            position=[0, 0, 6, 0, 6, 6, 0, 6],
        )
        self.assertAlmostEqual(
            compute_page_quantities({"a": condition}, [parent, same_page])["a"][0], 0.75
        )

    def test_an_area_child_without_geometry_does_not_subtract(self):
        parent = Takeoff(
            uid="p",
            condition_uid="a",
            page_uid="pg",
            position=[0, 0, 10, 0, 10, 10, 0, 10],
        )
        hole = Takeoff(
            uid="h", condition_uid="a", page_uid="pg", parent_uid="p", position=[]
        )
        self.assertEqual(
            compute_page_quantities({"a": self.area_condition()}, [parent, hole])["a"][
                0
            ],
            100.0,
        )


class TakeoffCubicYardsTests(unittest.TestCase):
    def test_cubic_yards_use_thickness_for_areas_and_height_for_other_types(self):
        from ost_visualizer.domain.services.condition_quantity_service import (
            compute_takeoff_cubic_yards,
        )

        area = Condition(
            uid="a", condition_type=Condition.TYPE_AREA, thickness=46656.0 / 144.0
        )
        takeoff = Takeoff(
            uid="t", condition_uid="a", position=[0, 0, 12, 0, 12, 12, 0, 12]
        )
        self.assertAlmostEqual(compute_takeoff_cubic_yards(area, takeoff), 1.0)
        # Distinct height and thickness: the volume is length * height * thickness, so a
        # swapped or duplicated dimension changes it (36 * 18 * 36 cubic inches = 0.5 cu yd).
        linear = Condition(
            uid="l", condition_type=Condition.TYPE_LINEAR, height=18.0, thickness=36.0
        )
        wall = Takeoff(uid="w", condition_uid="l", position=[0, 0, 36, 0])
        self.assertAlmostEqual(compute_takeoff_cubic_yards(linear, wall), 0.5)

    def test_negative_takeoffs_report_negative_volume_and_holes_are_subtracted(self):
        from ost_visualizer.domain.services.condition_quantity_service import (
            compute_takeoff_cubic_yards,
        )

        area = Condition(
            uid="a", condition_type=Condition.TYPE_AREA, thickness=46656.0 / 144.0
        )
        outer = Takeoff(
            uid="t", condition_uid="a", position=[0, 0, 12, 0, 12, 12, 0, 12]
        )
        hole = Takeoff(uid="h", condition_uid="a", position=[0, 0, 6, 0, 6, 6, 0, 6])
        self.assertAlmostEqual(
            compute_takeoff_cubic_yards(area, outer, [hole]), 108 / 144
        )
        self.assertAlmostEqual(compute_takeoff_cubic_yards(area, outer, None), 1.0)
        self.assertAlmostEqual(compute_takeoff_cubic_yards(area, outer, []), 1.0)
        outer.is_negative = True
        self.assertAlmostEqual(
            compute_takeoff_cubic_yards(area, outer, [hole]), -108 / 144
        )


class ConditionQuantityRootSentinelTests(unittest.TestCase):
    def test_root_sentinel_parents_never_make_a_takeoff_the_hole_of_a_takeoff_named_like_the_sentinel(
        self,
    ):
        condition = Condition(
            uid="a",
            condition_type=Condition.TYPE_AREA,
            calc_type1=CALC_AREA,
            uom1=UOM_SQUARE_INCHES,
        )
        zero = Takeoff(
            uid="0",
            condition_uid="a",
            page_uid="pg",
            parent_uid="",
            position=[0, 0, 10, 0, 10, 10, 0, 10],
        )
        none_named = Takeoff(
            uid="None",
            condition_uid="a",
            page_uid="pg",
            parent_uid="",
            position=[0, 0, 10, 0, 10, 10, 0, 10],
        )
        roots = [
            Takeoff(
                uid=f"r{i}",
                condition_uid="a",
                page_uid="pg",
                parent_uid=parent,
                position=[0, 0, 2, 0, 2, 2, 0, 2],
            )
            for i, parent in enumerate(("0", "None", "0"))
        ]
        total = compute_page_quantities({"a": condition}, [zero, none_named, *roots])
        self.assertEqual(total["a"][0], 100.0 + 100.0 + 3 * 4.0)

    def test_a_takeoff_with_a_blank_uid_does_not_adopt_the_blank_parent_roots_as_holes(
        self,
    ):
        condition = Condition(
            uid="a",
            condition_type=Condition.TYPE_AREA,
            calc_type1=CALC_AREA,
            uom1=UOM_SQUARE_INCHES,
        )
        takeoffs = [
            Takeoff(
                uid=uid,
                condition_uid="a",
                page_uid="pg",
                parent_uid="",
                position=position,
            )
            for uid, position in (
                ("", [0, 0, 10, 0, 10, 10, 0, 10]),
                ("r1", [0, 0, 2, 0, 2, 2, 0, 2]),
                ("r2", [0, 0, 2, 0, 2, 2, 0, 2]),
            )
        ]
        total = compute_page_quantities({"a": condition}, takeoffs)
        self.assertEqual(total["a"][0], 100.0 + 4.0 + 4.0)


class EverySupportedConditionTypeQuantityTests(unittest.TestCase):
    SQUARE = [0, 0, 10, 0, 10, 10, 0, 10]

    def quantities(self, condition_type, calc_type, uom, position, **dimensions):
        condition = Condition(
            uid="c",
            condition_type=condition_type,
            calc_type1=calc_type,
            uom1=uom,
            **dimensions,
        )
        takeoff = Takeoff(uid="t", condition_uid="c", position=position)
        return compute_page_quantities({"c": condition}, [takeoff])["c"]

    def test_linear_condition_measures_the_polyline_length(self):
        self.assertEqual(
            self.quantities(Condition.TYPE_LINEAR, 1, 1, [0, 0, 5, 0])[0], 5.0
        )

    def test_area_condition_measures_the_polygon_area(self):
        self.assertEqual(
            self.quantities(
                Condition.TYPE_AREA, CALC_AREA, UOM_SQUARE_INCHES, self.SQUARE
            )[0],
            100.0,
        )

    def test_count_and_attachment_conditions_count_one_per_takeoff(self):
        for condition_type in (Condition.TYPE_COUNT, Condition.TYPE_ATTACHMENT):
            with self.subTest(condition_type=condition_type):
                self.assertEqual(
                    self.quantities(condition_type, CALC_COUNT, 0, [5, 5])[0], 1.0
                )

    def test_count_like_conditions_ignore_polygon_geometry(self):
        for condition_type in (Condition.TYPE_COUNT, Condition.TYPE_ATTACHMENT):
            with self.subTest(condition_type=condition_type):
                self.assertEqual(
                    self.quantities(condition_type, CALC_COUNT, 0, self.SQUARE)[0],
                    1.0,
                )


class UnsupportedConditionTypePageTests(unittest.TestCase):
    SQUARE = [0, 0, 10, 0, 10, 10, 0, 10]

    def conditions(self, bad_type=7):
        return {
            "good": Condition(
                uid="good",
                name="Slab",
                condition_type=Condition.TYPE_AREA,
                calc_type1=CALC_AREA,
                uom1=UOM_SQUARE_INCHES,
            ),
            "bad": Condition(
                uid="bad",
                name="Foreign",
                condition_type=bad_type,
                calc_type1=CALC_AREA,
                uom1=UOM_SQUARE_INCHES,
            ),
        }

    def takeoffs(self):
        return [
            Takeoff(uid="1", condition_uid="good", position=self.SQUARE),
            Takeoff(uid="2", condition_uid="bad", position=self.SQUARE),
            Takeoff(uid="3", condition_uid="bad", position=self.SQUARE),
        ]

    def test_an_unsupported_condition_is_skipped_and_the_rest_of_the_page_is_kept(self):
        for bad_type in (-1, 4, 7, 99):
            with self.subTest(bad_type=bad_type):
                with self.assertLogs(
                    "ost_visualizer.domain.services.condition_quantity_service",
                    level="WARNING",
                ):
                    result = compute_page_quantities(
                        self.conditions(bad_type), self.takeoffs()
                    )
                self.assertEqual(result["good"][0], 100.0)
                self.assertEqual(result["bad"], (0.0, 0.0, 0.0))

    def test_the_skipped_condition_is_named_once_per_call_with_its_type(self):
        with self.assertLogs(
            "ost_visualizer.domain.services.condition_quantity_service",
            level="WARNING",
        ) as logged:
            compute_page_quantities(self.conditions(7), self.takeoffs())
        messages = [record.getMessage() for record in logged.records]
        self.assertEqual(len(messages), 1)
        self.assertIn("bad", messages[0])
        self.assertIn("Foreign", messages[0])
        self.assertIn("7", messages[0])

    def test_the_filtered_request_for_an_unsupported_condition_is_zero_not_missing(
        self,
    ):
        with self.assertLogs(
            "ost_visualizer.domain.services.condition_quantity_service",
            level="WARNING",
        ):
            result = compute_page_quantities(
                self.conditions(), self.takeoffs(), {"bad", "good"}
            )
        self.assertEqual(result["bad"], (0.0, 0.0, 0.0))
        self.assertEqual(result["good"][0], 100.0)

    def test_a_supported_page_logs_nothing(self):
        with self.assertNoLogs(
            "ost_visualizer.domain.services.condition_quantity_service",
            level="WARNING",
        ):
            compute_page_quantities(
                self.conditions(Condition.TYPE_AREA), self.takeoffs()
            )

    def test_a_cubic_yard_request_for_an_unsupported_condition_is_a_value_error(self):
        from ost_visualizer.domain.services.condition_quantity_service import (
            compute_takeoff_cubic_yards,
        )

        with self.assertRaises(ValueError):
            compute_takeoff_cubic_yards(
                self.conditions(7)["bad"],
                Takeoff(uid="2", condition_uid="bad", position=self.SQUARE),
            )


class UnsupportedConditionTypeBoundaryTests(unittest.TestCase):
    LOGGER = "ost_visualizer.domain.services.condition_quantity_service"
    SQUARE = [0, 0, 10, 0, 10, 10, 0, 10]

    def area(self, uid="good", **changes):
        base = dict(
            uid=uid,
            name="Slab",
            condition_type=Condition.TYPE_AREA,
            calc_type1=CALC_AREA,
            uom1=UOM_SQUARE_INCHES,
        )
        base.update(changes)
        return Condition(**base)

    def foreign(self, uid="bad", name="Foreign", condition_type=7):
        return Condition(
            uid=uid,
            name=name,
            condition_type=condition_type,
            calc_type1=CALC_AREA,
            uom1=UOM_SQUARE_INCHES,
        )

    def test_the_warning_is_one_exact_warning_level_message_from_the_service_logger(
        self,
    ):
        takeoffs = [
            Takeoff(uid="1", condition_uid="bad", position=self.SQUARE),
            Takeoff(uid="2", condition_uid="bad", position=self.SQUARE),
        ]
        with self.assertLogs(self.LOGGER, level="WARNING") as logged:
            compute_page_quantities({"bad": self.foreign()}, takeoffs)
        self.assertEqual(
            [(r.levelname, r.name, r.getMessage()) for r in logged.records],
            [
                (
                    "WARNING",
                    self.LOGGER,
                    "Skipping quantities for condition bad ('Foreign'): "
                    "unsupported condition type 7",
                )
            ],
        )

    def test_each_unsupported_condition_gets_its_own_warning_and_zero_entry(self):
        conditions = {
            "good": self.area(),
            "bad": self.foreign("bad", "First", 7),
            "worse": self.foreign("worse", "Second", -3),
        }
        takeoffs = [
            Takeoff(uid="1", condition_uid="bad", position=self.SQUARE),
            Takeoff(
                uid="2", condition_uid="worse", position=self.SQUARE, is_negative=True
            ),
            Takeoff(uid="3", condition_uid="good", position=self.SQUARE),
        ]
        with self.assertLogs(self.LOGGER, level="WARNING") as logged:
            result = compute_page_quantities(conditions, takeoffs)
        self.assertEqual(sorted(result), ["bad", "good", "worse"])
        self.assertEqual(result["good"], (100.0, 0.0, 0.0))
        for uid in ("bad", "worse"):
            self.assertEqual(result[uid], (0.0, 0.0, 0.0))
            for value in result[uid]:
                # A negative takeoff must not leave a negative zero behind.
                self.assertEqual(math.copysign(1.0, value), 1.0)
        messages = sorted(record.getMessage() for record in logged.records)
        self.assertEqual(
            messages,
            [
                "Skipping quantities for condition bad ('First'): "
                "unsupported condition type 7",
                "Skipping quantities for condition worse ('Second'): "
                "unsupported condition type -3",
            ],
        )

    def test_an_unsupported_condition_outside_the_requested_filter_is_ignored_silently(
        self,
    ):
        conditions = {"good": self.area(), "bad": self.foreign()}
        takeoffs = [
            Takeoff(uid="1", condition_uid="bad", position=self.SQUARE),
            Takeoff(uid="2", condition_uid="good", position=self.SQUARE),
        ]
        with self.assertNoLogs(self.LOGGER, level="WARNING"):
            result = compute_page_quantities(conditions, takeoffs, {"good"})
        self.assertEqual(result, {"good": (100.0, 0.0, 0.0)})

    def test_an_unsupported_condition_without_takeoffs_is_only_present_when_requested(
        self,
    ):
        conditions = {"bad": self.foreign()}
        with self.assertNoLogs(self.LOGGER, level="WARNING"):
            self.assertEqual(compute_page_quantities(conditions, []), {})
            self.assertEqual(
                compute_page_quantities(conditions, [], {"bad"}),
                {"bad": (0.0, 0.0, 0.0)},
            )

    def test_a_missing_condition_type_is_unsupported_not_a_crash(self):
        conditions = {"bad": self.foreign(condition_type=None)}
        takeoffs = [Takeoff(uid="1", condition_uid="bad", position=self.SQUARE)]
        with self.assertLogs(self.LOGGER, level="WARNING") as logged:
            result = compute_page_quantities(conditions, takeoffs)
        self.assertEqual(result, {"bad": (0.0, 0.0, 0.0)})
        self.assertTrue(logged.records[0].getMessage().endswith("type None"))

    def test_a_child_of_an_unsupported_type_never_changes_a_supported_parent(self):
        for bad_type in (Condition.TYPE_ATTACHMENT + 5, -1):
            with self.subTest(bad_type=bad_type):
                bad = self.foreign(condition_type=bad_type)
                bad.width = 2
                bad.depth = 3
                conditions = {"good": self.area(calc_type1=12), "bad": bad}
                parent = Takeoff(
                    uid="p", condition_uid="good", page_uid="pg", position=self.SQUARE
                )
                child = Takeoff(
                    uid="c",
                    condition_uid="bad",
                    page_uid="pg",
                    parent_uid="p",
                    position=[1, 1, 3, 1, 3, 3, 1, 3],
                )
                with self.assertLogs(self.LOGGER, level="WARNING"):
                    result = compute_page_quantities(conditions, [parent, child])
                self.assertEqual(result["good"], (100.0, 0.0, 0.0))
                self.assertEqual(result["bad"], (0.0, 0.0, 0.0))

    def test_an_empty_page_has_no_entries_whatever_the_request(self):
        self.assertEqual(compute_page_quantities({}, []), {})
        self.assertEqual(compute_page_quantities({}, [], {"x"}), {})
        self.assertEqual(compute_page_quantities({"good": self.area()}, []), {})


class ChildKindAndRoundingBoundaryTests(unittest.TestCase):
    SQUARE = [0, 0, 10, 0, 10, 10, 0, 10]

    def attachment_aware_area(self):
        return Condition(
            uid="a",
            condition_type=Condition.TYPE_AREA,
            calc_type1=12,
            uom1=UOM_SQUARE_INCHES,
        )

    def child_of(self, condition_type, **dimensions):
        condition = Condition(
            uid="k", condition_type=condition_type, calc_type1=CALC_COUNT, **dimensions
        )
        takeoff = Takeoff(
            uid="c",
            condition_uid="k",
            page_uid="pg",
            parent_uid="p",
            position=[5, 5],
        )
        return condition, takeoff

    def test_only_attachment_children_contribute_a_footprint_to_the_parent(self):
        parent = Takeoff(
            uid="p", condition_uid="a", page_uid="pg", position=self.SQUARE
        )
        expected = {
            Condition.TYPE_ATTACHMENT: 100.0 - 6.0,
            Condition.TYPE_LINEAR: 100.0,
            Condition.TYPE_COUNT: 100.0,
        }
        for condition_type, area in expected.items():
            with self.subTest(child_type=condition_type):
                condition, child = self.child_of(condition_type, width=2, depth=3)
                result = compute_page_quantities(
                    {"a": self.attachment_aware_area(), "k": condition},
                    [parent, child],
                    {"a"},
                )
                self.assertEqual(result, {"a": (area, 0.0, 0.0)})

    def test_an_area_takeoff_whose_parent_is_not_on_the_page_is_not_counted(self):
        # Characterisation of current behaviour (not a stated requirement): a child whose
        # parent is missing is neither a primary nor a hole, so it vanishes from the totals.
        area = self.attachment_aware_area()
        area.calc_type1 = CALC_AREA
        takeoffs = [
            Takeoff(uid="p", condition_uid="a", page_uid="pg", position=self.SQUARE),
            Takeoff(
                uid="orphan",
                condition_uid="a",
                page_uid="pg",
                parent_uid="missing",
                position=[0, 0, 2, 0, 2, 2, 0, 2],
            ),
        ]
        self.assertEqual(
            compute_page_quantities({"a": area}, takeoffs), {"a": (100.0, 0.0, 0.0)}
        )
        self.assertEqual(
            compute_page_quantities({"a": area}, takeoffs[1:]), {"a": (0.0, 0.0, 0.0)}
        )

    def test_rounding_applies_to_each_takeoff_before_its_sign(self):
        linear = Condition(
            uid="l",
            condition_type=Condition.TYPE_LINEAR,
            calc_type1=1,
            uom1=1,
            round_quantity=True,
            round_up=12.0,
        )
        takeoffs = [
            Takeoff(uid="1", condition_uid="l", position=[0, 0, 13, 0]),
            Takeoff(uid="2", condition_uid="l", position=[0, 0, 13, 0]),
            Takeoff(
                uid="3", condition_uid="l", position=[0, 0, 5, 0], is_negative=True
            ),
        ]
        # Per takeoff: 13 -> 24, 13 -> 24, 5 -> 12 (negative), so 24 + 24 - 12 = 36.
        # Rounding the net length instead (13 + 13 - 5 = 21) would give 24.
        self.assertEqual(compute_page_quantities({"l": linear}, takeoffs)["l"][0], 36.0)
        self.assertEqual(
            compute_page_quantities({"l": linear}, takeoffs[2:])["l"][0], -12.0
        )

    def test_a_takeoff_without_geometry_totals_zero(self):
        cases = (
            (Condition.TYPE_LINEAR, 1, 1),
            (Condition.TYPE_AREA, CALC_AREA, UOM_SQUARE_INCHES),
        )
        for condition_type, calc_type, uom in cases:
            with self.subTest(condition_type=condition_type):
                condition = Condition(
                    uid="c",
                    condition_type=condition_type,
                    calc_type1=calc_type,
                    uom1=uom,
                )
                takeoff = Takeoff(uid="t", condition_uid="c", position=[])
                self.assertEqual(
                    compute_page_quantities({"c": condition}, [takeoff]),
                    {"c": (0.0, 0.0, 0.0)},
                )

    def test_very_large_geometry_is_summed_without_overflow(self):
        condition = Condition(
            uid="c",
            condition_type=Condition.TYPE_AREA,
            calc_type1=CALC_AREA,
            uom1=UOM_SQUARE_INCHES,
        )
        side = 1e12
        big = Takeoff(
            uid="t", condition_uid="c", position=[0, 0, side, 0, side, side, 0, side]
        )
        twice = compute_page_quantities({"c": condition}, [big, big])["c"][0]
        self.assertAlmostEqual(twice / 2e24, 1.0)


class ForwardedConditionParameterTests(unittest.TestCase):
    """Every Condition/Takeoff parameter reaches the calculator, slot by slot."""

    BOX = [0, 0, 22, 0, 22, 10, 0, 10]

    def page(self, condition, takeoff):
        return compute_page_quantities({"c": condition}, [takeoff])["c"]

    def test_rise_and_run_scale_area_and_perimeter_by_the_absolute_slope(self):
        for rise, run in ((3.0, 4.0), (-3.0, 4.0), (3.0, -4.0)):
            with self.subTest(rise=rise, run=run):
                condition = Condition(
                    uid="c",
                    condition_type=Condition.TYPE_AREA,
                    calc_type1=CALC_AREA,
                    uom1=UOM_SQUARE_INCHES,
                    calc_type2=14,
                    uom2=UOM_EACH,
                    rise=rise,
                    run=run,
                )
                takeoff = Takeoff(
                    uid="t", condition_uid="c", position=[0, 0, 10, 0, 10, 10, 0, 10]
                )
                self.assertEqual(self.page(condition, takeoff), (125.0, 50.0, 0.0))

    def test_rise_and_run_scale_a_linear_length_only_for_a_positive_slope(self):
        for rise, run, expected in (
            (3.0, 4.0, 12.5),
            (-3.0, 4.0, 10.0),
            (3.0, 0.0, 10.0),
        ):
            with self.subTest(rise=rise, run=run):
                condition = Condition(
                    uid="c",
                    condition_type=Condition.TYPE_LINEAR,
                    calc_type1=1,
                    uom1=UOM_EACH,
                    rise=rise,
                    run=run,
                )
                takeoff = Takeoff(uid="t", condition_uid="c", position=[0, 0, 10, 0])
                self.assertEqual(self.page(condition, takeoff)[0], expected)

    def test_grid_sizes_and_gap_reach_the_grid_quantities_in_slot_order(self):
        # Units are 3 + 1 = 4 and 1 + 1 = 2 on a 22 x 10 box of area 220.
        condition = Condition(
            uid="c",
            condition_type=Condition.TYPE_AREA,
            calc_type1=18,
            uom1=UOM_EACH,
            calc_type2=16,
            uom2=UOM_EACH,
            calc_type3=17,
            uom3=UOM_EACH,
            grid_size1=3.0,
            grid_size2=1.0,
            gap=1.0,
        )
        takeoff = Takeoff(uid="t", condition_uid="c", position=self.BOX)
        q = self.page(condition, takeoff)
        self.assertEqual(q[0], 5 * 5)  # floor(22/4) * floor(10/2)
        self.assertEqual(q[1], 6 * 10 + 5 * 22)  # ceil(22/4)*10 + ceil(10/2)*22
        self.assertEqual(q[2], 220 / 8)

    def test_a_different_gap_and_swapped_grid_sizes_change_those_quantities(self):
        condition = Condition(
            uid="c",
            condition_type=Condition.TYPE_AREA,
            calc_type1=18,
            uom1=UOM_EACH,
            calc_type2=16,
            uom2=UOM_EACH,
            calc_type3=17,
            uom3=UOM_EACH,
            grid_size1=1.0,
            grid_size2=3.0,
            gap=0.0,
        )
        takeoff = Takeoff(uid="t", condition_uid="c", position=self.BOX)
        q = self.page(condition, takeoff)
        self.assertEqual(q[0], 22 * 3)  # floor(22/1) * floor(10/3)
        self.assertEqual(q[1], 22 * 10 + 4 * 22)  # ceil(22/1)*10 + ceil(10/3)*22
        self.assertEqual(q[2], 220 / 3)

    def test_an_enabled_curve_lengthens_the_linear_quantity_and_curve_minus_one_does_not(
        self,
    ):
        condition = Condition(
            uid="c", condition_type=Condition.TYPE_LINEAR, calc_type1=1, uom1=UOM_EACH
        )
        position = [0, 0, 10, 0, 5, 5]
        for curve, expected in ((-1, 10.0), (0, 15.576465376942007)):
            with self.subTest(curve=curve):
                takeoff = Takeoff(
                    uid="t", condition_uid="c", position=position, curve=curve
                )
                self.assertAlmostEqual(self.page(condition, takeoff)[0], expected)

    def test_round_up_is_ignored_unless_rounding_is_switched_on(self):
        takeoff = Takeoff(uid="t", condition_uid="c", position=[0, 0, 13, 0])
        for enabled, expected in ((False, 13.0), (True, 24.0)):
            with self.subTest(round_quantity=enabled):
                condition = Condition(
                    uid="c",
                    condition_type=Condition.TYPE_LINEAR,
                    calc_type1=1,
                    uom1=UOM_EACH,
                    round_quantity=enabled,
                    round_up=12.0,
                )
                self.assertEqual(self.page(condition, takeoff)[0], expected)

    def test_count_dimensions_and_per_slot_units_are_forwarded(self):
        condition = Condition(
            uid="c",
            condition_type=Condition.TYPE_COUNT,
            width=4.0,
            height=7.0,
            depth=3.0,
            calc_type1=CALC_WIDTH_SIDE,
            uom1=UOM_EACH,
            calc_type2=CALC_DEPTH_SIDE,
            uom2=UOM_LINEAR_FEET,
            calc_type3=CALC_HEIGHT_OR_LENGTH,
            uom3=UOM_LINEAR_YARDS,
        )
        takeoff = Takeoff(uid="t", condition_uid="c", position=[1, 1])
        q = self.page(condition, takeoff)
        self.assertAlmostEqual(q[0], 4.0 * 7.0)
        self.assertAlmostEqual(q[1], 3.0 * 7.0 / 12.0)
        self.assertAlmostEqual(q[2], 7.0 / 36.0)


class PageUidComparisonTests(unittest.TestCase):
    SQUARE = [0, 0, 10, 0, 10, 10, 0, 10]
    HOLE = [0, 0, 2, 0, 2, 2, 0, 2]

    def condition(self):
        return Condition(
            uid="c",
            condition_type=Condition.TYPE_AREA,
            calc_type1=CALC_AREA,
            uom1=UOM_SQUARE_INCHES,
        )

    def net(self, parent_page, child_page):
        parent = Takeoff(
            uid="p", condition_uid="c", page_uid=parent_page, position=self.SQUARE
        )
        hole = Takeoff(
            uid="h",
            condition_uid="c",
            page_uid=child_page,
            parent_uid="p",
            position=self.HOLE,
        )
        return compute_page_quantities({"c": self.condition()}, [parent, hole])["c"][0]

    def test_equal_but_distinct_page_uid_objects_are_the_same_page(self):
        first, second = "".join(["pa", "ge"]), "".join(["pa", "ge"])
        self.assertIsNot(first, second)
        self.assertEqual(self.net(first, second), 96.0)

    def test_page_uids_match_by_equality_not_by_prefix_or_emptiness(self):
        for other in ("page-1", "", "page-100", "PAGE-10"):
            with self.subTest(child_page=other):
                self.assertEqual(self.net("page-10", other), 100.0)
        self.assertEqual(self.net("page-10", "page-10"), 96.0)


class CubicYardForwardingTests(unittest.TestCase):
    CY = 46656.0  # cubic inches per cubic yard

    def area(self, **changes):
        base = dict(uid="a", condition_type=Condition.TYPE_AREA, thickness=324.0)
        base.update(changes)
        return Condition(**base)

    def square(self, uid="t"):
        return Takeoff(
            uid=uid, condition_uid="a", position=[0, 0, 12, 0, 12, 12, 0, 12]
        )

    def test_slope_scales_the_volume(self):
        self.assertAlmostEqual(
            compute_takeoff_cubic_yards(self.area(rise=3.0, run=4.0), self.square()),
            1.25,
        )

    def test_rounding_applies_to_the_cubic_yards_and_keeps_the_sign(self):
        condition = self.area(round_quantity=True, round_up=2 * self.CY)
        takeoff = self.square()
        self.assertAlmostEqual(compute_takeoff_cubic_yards(condition, takeoff), 2.0)
        takeoff.is_negative = True
        self.assertAlmostEqual(compute_takeoff_cubic_yards(condition, takeoff), -2.0)

    def test_round_up_is_ignored_unless_rounding_is_switched_on(self):
        condition = self.area(round_quantity=False, round_up=2 * self.CY)
        self.assertAlmostEqual(
            compute_takeoff_cubic_yards(condition, self.square()), 1.0
        )

    def test_linear_volume_follows_slope_curve_and_rounding(self):
        linear = Condition(
            uid="l", condition_type=Condition.TYPE_LINEAR, height=1.0, thickness=1.0
        )
        straight = Takeoff(uid="s", condition_uid="l", position=[0, 0, 10, 0, 5, 5])
        curved = Takeoff(
            uid="k", condition_uid="l", position=[0, 0, 10, 0, 5, 5], curve=0
        )
        self.assertAlmostEqual(
            compute_takeoff_cubic_yards(linear, straight), 10.0 / self.CY
        )
        self.assertAlmostEqual(
            compute_takeoff_cubic_yards(linear, curved), 15.576465376942007 / self.CY
        )
        sloped = Condition(
            uid="l",
            condition_type=Condition.TYPE_LINEAR,
            height=1.0,
            thickness=1.0,
            rise=3.0,
            run=4.0,
        )
        wall = Takeoff(uid="w", condition_uid="l", position=[0, 0, 10, 0])
        self.assertAlmostEqual(
            compute_takeoff_cubic_yards(sloped, wall), 12.5 / self.CY
        )
        rounded = Condition(
            uid="l",
            condition_type=Condition.TYPE_LINEAR,
            height=1.0,
            thickness=1.0,
            round_quantity=True,
            round_up=self.CY,
        )
        self.assertAlmostEqual(compute_takeoff_cubic_yards(rounded, wall), 1.0)

    def test_count_volume_is_width_times_depth_times_height(self):
        count = Condition(
            uid="c",
            condition_type=Condition.TYPE_COUNT,
            width=4.0,
            height=7.0,
            depth=3.0,
        )
        point = Takeoff(uid="t", condition_uid="c", position=[1, 1])
        self.assertAlmostEqual(
            compute_takeoff_cubic_yards(count, point), 84.0 / self.CY
        )

    def test_unused_quantity_slots_cannot_make_the_volume_fail(self):
        # Slots two and three are computed but discarded. A denormal round_up would
        # overflow any slot that measured something, so this only passes while the
        # unused slots measure nothing.
        linear = Condition(
            uid="l",
            condition_type=Condition.TYPE_LINEAR,
            height=0.0,
            thickness=0.0,
            round_quantity=True,
            round_up=5e-324,
        )
        wall = Takeoff(uid="w", condition_uid="l", position=[0, 0, 5, 0])
        self.assertEqual(compute_takeoff_cubic_yards(linear, wall), 0.0)


class CurvedHoleTests(unittest.TestCase):
    def test_an_area_hole_whose_curve_flag_is_zero_is_still_subtracted(self):
        # curve=0 is Takeoff.CURVE_ENABLED (falsy) and curve=-1 is "no curve" (truthy), so
        # any guard that tests the hole's curve instead of its geometry silently drops a
        # curved hole. The hole's own curve does not change the parent's net area.
        condition = Condition(
            uid="c",
            condition_type=Condition.TYPE_AREA,
            calc_type1=CALC_AREA,
            uom1=UOM_SQUARE_INCHES,
        )
        parent = Takeoff(
            uid="p",
            condition_uid="c",
            page_uid="pg",
            position=[0, 0, 10, 0, 10, 10, 0, 10],
        )
        for curve in (0, -1):
            with self.subTest(hole_curve=curve):
                hole = Takeoff(
                    uid="h",
                    condition_uid="c",
                    page_uid="pg",
                    parent_uid="p",
                    curve=curve,
                    position=[0, 0, 2, 0, 2, 2, 0, 2],
                )
                result = compute_page_quantities({"c": condition}, [parent, hole])
                self.assertEqual(result["c"][0], 96.0)
