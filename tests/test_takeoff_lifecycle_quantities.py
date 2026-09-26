import unittest
from dataclasses import replace
from xml.etree.ElementTree import Element
from ost_visualizer.application.use_cases.project.condition_summary_service import (
    ConditionSummaryService,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.condition_quantity_service import (
    compute_page_quantities,
)
from ost_visualizer.domain.services.uom_service import (
    CALC_AREA,
    CALC_COUNT,
    UOM_SQUARE_INCHES,
)
from ost_visualizer.domain.services.takeoff_domain_service import (
    is_takeoff_relevant_for_area_usage,
)
from ost_visualizer.domain.services import uom_service
from ost_visualizer.infrastructure.mdb.exporters.ost_exporter import OstExporter


class TakeoffLifecycleQuantityTests(unittest.TestCase):
    def test_mcp_quantity_count_includes_attachment_and_excludes_area_backout(self):
        from ost_visualizer.application.services.mcp_read_service import McpReadService

        service = McpReadService.__new__(McpReadService)
        quantities = {uid: (1, 0, 0) for uid in self.conditions}
        results = service._quantity_dtos(quantities, self.conditions, self.takeoffs)
        counts = {row.condition_uid: row.takeoff_count for row in results}
        self.assertEqual(counts, {"area": 1, "backout": 0, "attachment": 1})

    def test_ost_export_matches_signed_quantities_and_cross_condition_backouts(self):
        conditions = [
            {
                "UID": "area",
                "Type": "1",
                "Quantity1": str(CALC_AREA),
                "UOM1": str(UOM_SQUARE_INCHES),
            },
            {
                "UID": "backout",
                "Type": "1",
                "Quantity1": str(CALC_AREA),
                "UOM1": str(UOM_SQUARE_INCHES),
            },
            {"UID": "point", "Type": "3", "Quantity1": str(CALC_COUNT)},
        ]
        takeoffs = [
            {
                "UID": "1",
                "BidConditionUID": "area",
                "ParentUID": "0",
                "Position": "0;0;10;0;10;10;0;10",
                "IsNegativeQuantity": "True",
            },
            {
                "UID": "2",
                "BidConditionUID": "backout",
                "ParentUID": "1",
                "Position": "1;1;3;1;3;3;1;3",
            },
            {
                "UID": "3",
                "BidConditionUID": "point",
                "ParentUID": "1",
                "Position": "5;5",
                "IsNegativeQuantity": "-1",
            },
        ]
        root = Element("Bid")
        OstExporter(uom_service)._build_conditions_section(
            root, conditions, {}, {"BidTakeoffs": takeoffs}
        )
        quantities = {
            row.get("UID"): float(
                row.find("./BidAreaConditions/BidAreaCondition").get("Quantity1")
            )
            for row in root.findall("./BidConditions/BidCondition")
        }
        self.assertEqual(quantities["area"], -96)
        self.assertEqual(quantities["point"], -1)

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

    def test_attachment_assignment_participates_in_bid_area_usage(self):
        attachment = self.takeoffs[-1]
        attachment.area_uid = "attachment-area"
        self.assertTrue(is_takeoff_relevant_for_area_usage(attachment, self.conditions))
        self.assertFalse(
            is_takeoff_relevant_for_area_usage(self.takeoffs[1], self.conditions)
        )

    def test_scoped_area_quantities_include_backout_on_another_condition(self):
        full = compute_page_quantities(self.conditions, self.takeoffs)
        scoped = compute_page_quantities(self.conditions, self.takeoffs, {"area"})
        self.assertEqual(full["area"][0], 96)
        self.assertEqual(scoped["area"], full["area"])

    def test_summary_attachment_context_retains_own_condition_and_parent_area_dependencies(
        self,
    ):
        service = ConditionSummaryService()
        contexts = service._build_takeoff_contexts(self.conditions, self.takeoffs)
        by_condition = {context.condition_uid: context for context in contexts}
        self.assertIn("attachment", by_condition)
        self.assertEqual(
            service._quantities_for_contexts(
                self.conditions, "attachment", [by_condition["attachment"]]
            )[0],
            1,
        )
        self.assertEqual(
            service._quantities_for_contexts(
                self.conditions, "area", [by_condition["area"]]
            )[0],
            96,
        )

    def test_attachment_aware_area_formula_uses_child_dimensions(self):
        self.conditions["area"] = replace(self.conditions["area"], calc_type1=12)
        self.assertEqual(
            compute_page_quantities(self.conditions, self.takeoffs)["area"][0], 92
        )
