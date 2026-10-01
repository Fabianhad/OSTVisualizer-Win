import unittest
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.takeoff_domain_service import (
    common_reassign_geometry_type,
    condition_reassign_geometry_type,
    takeoffs_can_reassign_to_condition,
)
from ost_visualizer.domain.services.uom_service import (
    CALC_AREA,
    CALC_COUNT,
    UOM_SQUARE_INCHES,
)
from ost_visualizer.domain.services.takeoff_domain_service import (
    is_takeoff_relevant_for_area_usage,
)


class TakeoffReassignmentPolicyTests(unittest.TestCase):
    def test_condition_reassignment_preserves_geometry_compatibility_policy(self):
        conditions = {
            "linear-a": Condition(uid="linear-a", condition_type=Condition.TYPE_LINEAR),
            "linear-b": Condition(uid="linear-b", condition_type=Condition.TYPE_LINEAR),
            "area-a": Condition(uid="area-a", condition_type=Condition.TYPE_AREA),
            "area-b": Condition(uid="area-b", condition_type=Condition.TYPE_AREA),
            "count": Condition(uid="count", condition_type=Condition.TYPE_COUNT),
            "attachment": Condition(
                uid="attachment", condition_type=Condition.TYPE_ATTACHMENT
            ),
        }
        linear = Takeoff(uid="linear", condition_uid="linear-a")
        area = Takeoff(uid="area", condition_uid="area-a")
        hole = Takeoff(uid="hole", condition_uid="area-a", parent_uid="area")
        count = Takeoff(uid="count", condition_uid="count")
        attachment = Takeoff(uid="attachment", condition_uid="attachment")
        self.assertTrue(
            takeoffs_can_reassign_to_condition([linear], conditions, "linear-b")
        )
        self.assertTrue(
            takeoffs_can_reassign_to_condition([area, hole], conditions, "area-b")
        )
        self.assertFalse(
            takeoffs_can_reassign_to_condition([linear], conditions, "area-b")
        )
        self.assertFalse(
            takeoffs_can_reassign_to_condition([area], conditions, "linear-b")
        )
        self.assertTrue(
            takeoffs_can_reassign_to_condition([count], conditions, "attachment")
        )
        self.assertTrue(
            takeoffs_can_reassign_to_condition([attachment], conditions, "count")
        )
        self.assertIsNone(common_reassign_geometry_type([linear, area], conditions))
        self.assertFalse(
            takeoffs_can_reassign_to_condition([linear, area], conditions, "linear-b")
        )
        self.assertFalse(takeoffs_can_reassign_to_condition([], conditions, "linear-b"))
        self.assertFalse(
            takeoffs_can_reassign_to_condition([linear], conditions, "missing")
        )
        self.assertFalse(
            takeoffs_can_reassign_to_condition(
                [Takeoff("unknown", "missing")], conditions, "linear-b"
            )
        )
        self.assertEqual(
            condition_reassign_geometry_type(conditions["attachment"]),
            Condition.TYPE_COUNT,
        )


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

    def test_attachment_assignment_participates_in_bid_area_usage(self):
        attachment = self.takeoffs[-1]
        attachment.area_uid = "attachment-area"
        self.assertTrue(is_takeoff_relevant_for_area_usage(attachment, self.conditions))
        self.assertFalse(
            is_takeoff_relevant_for_area_usage(self.takeoffs[1], self.conditions)
        )
        self.conditions["attachment"].layer_visible = False
        self.assertFalse(
            is_takeoff_relevant_for_area_usage(attachment, self.conditions)
        )
        self.conditions["attachment"].layer_visible = True
        attachment.position = []
        self.assertFalse(
            is_takeoff_relevant_for_area_usage(attachment, self.conditions)
        )
        self.assertFalse(
            is_takeoff_relevant_for_area_usage(
                Takeoff("orphan", "missing", position=[1, 2]), self.conditions
            )
        )
