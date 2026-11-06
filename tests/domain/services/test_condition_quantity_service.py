import unittest
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.condition_quantity_service import (
    compute_page_quantities,
)
from dataclasses import replace
from ost_visualizer.domain.services.uom_service import (
    CALC_AREA,
    CALC_COUNT,
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

    def test_all_three_quantities_and_negative_signs_are_accumulated_per_condition(self):
        condition = self.area_condition(calc_type2=14, uom2=UOM_SQUARE_INCHES)
        positive = Takeoff(uid="1", condition_uid="a", position=[0, 0, 10, 0, 10, 10, 0, 10])
        negative = Takeoff(
            uid="2", condition_uid="a", position=[0, 0, 4, 0, 4, 4, 0, 4], is_negative=True
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

    def test_attachment_children_subtract_footprint_and_add_perimeter_to_the_parent(self):
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

    def test_a_child_that_is_neither_area_nor_attachment_does_not_affect_the_parent(self):
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
            uom1=UOM_SQUARE_FEET, uom2=UOM_SQUARE_FEET, calc_type3=CALC_AREA, uom3=UOM_SQUARE_FEET
        )
        positive = Takeoff(uid="1", condition_uid="a", position=[0, 0, 12, 0, 12, 9, 0, 9])
        negative = Takeoff(
            uid="2", condition_uid="a", position=[0, 0, 6, 0, 6, 6, 0, 6], is_negative=True
        )
        total = compute_page_quantities({"a": condition}, [positive, negative])["a"]
        self.assertAlmostEqual(total[0], 0.75 - 0.25)
        self.assertAlmostEqual(total[1], 0.75 - 0.25)
        self.assertAlmostEqual(total[2], 0.75 - 0.25)
        only_negative = compute_page_quantities({"a": condition}, [negative])["a"]
        self.assertAlmostEqual(only_negative[0], -0.25)
        self.assertAlmostEqual(only_negative[1], -0.25)
        self.assertAlmostEqual(only_negative[2], -0.25)

    def test_a_child_on_a_different_page_is_ignored_whichever_page_uid_sorts_first(self):
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
            compute_page_quantities({"a": self.area_condition()}, [parent, hole])["a"][0],
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
        linear = Condition(
            uid="l", condition_type=Condition.TYPE_LINEAR, height=36.0, thickness=36.0
        )
        wall = Takeoff(uid="w", condition_uid="l", position=[0, 0, 36, 0])
        self.assertAlmostEqual(compute_takeoff_cubic_yards(linear, wall), 1.0)

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
