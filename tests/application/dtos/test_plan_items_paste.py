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


class PreparePlanItemsPasteEdgeTests(unittest.TestCase):
    def spec(self, annotation_type="hotlink", target="view"):
        return InsertAnnotationSpec(
            "page", annotation_type, [1.0], "#000000", 1.0, {"BidPageViewUID": target}
        )

    def payload(self, *specs, sources=("hotlink/h",), destination="other"):
        return PlanItemsPastePayload(
            source_bid_uid="source",
            destination_bid_uid=destination,
            annotation_source_uids=tuple(sources),
            annotation_specs=tuple(specs),
        )

    def test_only_links_to_views_that_are_not_copied_along_are_cleared_across_bids(
        self,
    ):
        prepared = prepare_plan_items_paste_payload(
            self.payload(self.spec(target="view"))
        )
        self.assertIsNone(prepared.annotation_specs[0].properties["BidPageViewUID"])
        kept = prepare_plan_items_paste_payload(
            self.payload(
                self.spec(target="view"),
                self.spec(annotation_type="namedview", target=None),
                sources=("hotlink/h", "namedview/view"),
            )
        )
        self.assertEqual(kept.annotation_specs[0].properties["BidPageViewUID"], "view")
        numeric = prepare_plan_items_paste_payload(
            self.payload(
                self.spec(target=7),
                self.spec(annotation_type="namedview", target=None),
                sources=("hotlink/h", "namedview/7"),
            )
        )
        self.assertEqual(numeric.annotation_specs[0].properties["BidPageViewUID"], 7)

    def test_null_and_zero_targets_and_other_annotation_types_are_left_alone(self):
        for target in (None, "", 0, "0"):
            prepared = prepare_plan_items_paste_payload(
                self.payload(self.spec(target=target))
            )
            self.assertEqual(
                prepared.annotation_specs[0].properties["BidPageViewUID"], target
            )
        other = self.spec(annotation_type="rect", target="view")
        prepared = prepare_plan_items_paste_payload(
            self.payload(other, sources=("rect/r",))
        )
        self.assertEqual(
            prepared.annotation_specs[0].properties["BidPageViewUID"], "view"
        )

    def test_unchanged_cross_bid_payloads_are_returned_as_the_prepared_copy_and_only_changed_specs_differ(
        self,
    ):
        keep = self.spec(annotation_type="rect", target="view")
        clear = self.spec(target="gone")
        prepared = prepare_plan_items_paste_payload(
            self.payload(keep, clear, sources=("rect/r", "hotlink/h"))
        )
        self.assertEqual(
            prepared.annotation_specs[0].properties["BidPageViewUID"], "view"
        )
        self.assertIsNone(prepared.annotation_specs[1].properties["BidPageViewUID"])
        self.assertEqual(prepared.annotation_specs[1].position, [1.0])
        original = self.payload(keep, sources=("rect/r",))
        same = prepare_plan_items_paste_payload(original)
        self.assertIsNot(same, original)
        self.assertEqual(same, original)
        self.assertEqual(same.annotation_specs[0], keep)

    def test_cross_bid_clearing_applies_whichever_bid_uid_sorts_first(self):
        # Only inequality of the two bid uids matters, not their string order.
        for destination in ("a-before-source", "zz-after-source"):
            with self.subTest(destination=destination):
                prepared = prepare_plan_items_paste_payload(
                    self.payload(self.spec(target="view"), destination=destination)
                )
                self.assertIsNone(
                    prepared.annotation_specs[0].properties["BidPageViewUID"]
                )
        same_bid = prepare_plan_items_paste_payload(
            self.payload(self.spec(target="view"), destination="source")
        )
        self.assertEqual(
            same_bid.annotation_specs[0].properties["BidPageViewUID"], "view"
        )
