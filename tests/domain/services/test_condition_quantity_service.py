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
