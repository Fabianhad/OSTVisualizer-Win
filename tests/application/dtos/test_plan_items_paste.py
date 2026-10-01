import unittest
from ost_visualizer.application.dtos.collaboration_dtos import PlanItemsPastePayload
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.application.dtos.plan_items_paste import (
    prepare_plan_items_paste_payload,
)


class PreparePlanItemsPastePayloadTests(unittest.TestCase):
    @staticmethod
    def payload(destination="source", include_named_view=False):
        sources = ["hotlink/h"]
        specs = [
            InsertAnnotationSpec(
                "page",
                "hotlink",
                [1.0, 2.0],
                "#000000",
                1.0,
                {"BidPageViewUID": "view", "nested": ["original"]},
            )
        ]
        if include_named_view:
            sources.append("namedview/view")
            specs.append(
                InsertAnnotationSpec("page", "namedview", [0.0, 0.0], "#000000", 1.0)
            )
        return PlanItemsPastePayload(
            source_bid_uid="source",
            destination_bid_uid=destination,
            annotation_source_uids=tuple(sources),
            annotation_specs=tuple(specs),
        )

    def test_same_bid_preserves_link_but_snapshots_mutable_spec_data(self):
        original = self.payload()
        prepared = prepare_plan_items_paste_payload(original)
        original.annotation_specs[0].position[0] = 99.0
        original.annotation_specs[0].properties["nested"].append("later")
        self.assertEqual(prepared.annotation_specs[0].position, [1.0, 2.0])
        self.assertEqual(
            prepared.annotation_specs[0].properties["nested"], ["original"]
        )
        self.assertEqual(
            prepared.annotation_specs[0].properties["BidPageViewUID"], "view"
        )

    def test_cross_bid_clears_external_link_without_mutating_source(self):
        original = self.payload(destination="other")
        prepared = prepare_plan_items_paste_payload(original)
        self.assertIsNone(prepared.annotation_specs[0].properties["BidPageViewUID"])
        self.assertEqual(
            original.annotation_specs[0].properties["BidPageViewUID"], "view"
        )

    def test_cross_bid_retains_copied_named_view_dependency_and_is_repeatable(self):
        prepared = prepare_plan_items_paste_payload(
            self.payload(destination="other", include_named_view=True)
        )
        self.assertEqual(
            prepared.annotation_specs[0].properties["BidPageViewUID"], "view"
        )
        repeated = prepare_plan_items_paste_payload(prepared)
        self.assertEqual(repeated, prepared)
        prepared.annotation_specs[0].properties["nested"].append("later")
        prepared.annotation_specs[1].position[0] = 123
        self.assertEqual(
            repeated.annotation_specs[0].properties["nested"], ["original"]
        )
        self.assertEqual(repeated.annotation_specs[1].position, [0.0, 0.0])

    def test_takeoff_specs_and_parent_bindings_are_detached_from_caller(self):
        spec = InsertTakeoffSpec(
            "condition", "page", "area", [1.0, 2.0], parent_uid="parent"
        )
        original = PlanItemsPastePayload(
            source_bid_uid="source",
            destination_bid_uid="source",
            takeoff_source_uids=("child",),
            takeoff_specs=(spec,),
            takeoff_external_parent_sources=("child",),
        )
        prepared = prepare_plan_items_paste_payload(original)
        spec.position[0] = 99.0
        spec.condition_uid = "changed"
        spec.parent_uid = "different-parent"
        self.assertEqual(prepared.takeoff_specs[0].position, [1.0, 2.0])
        self.assertEqual(prepared.takeoff_specs[0].condition_uid, "condition")
        self.assertEqual(prepared.takeoff_specs[0].parent_uid, "parent")
        self.assertEqual(prepared.takeoff_external_parent_sources, ("child",))
