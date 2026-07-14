import unittest
from ost_visualizer.application.dtos.mcp_context_dtos import (
    MCP_BID_COMPARISON_DEFAULT_LIMIT,
    MCP_STATUS_DUPLICATE_REF_NO,
    McpBidDto,
)
from ost_visualizer.application.services.bid_comparison_service import (
    BidComparisonService,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.file_results import BidLoadResult
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.uom_service import (
    UOM_CUBIC_YARDS,
    UOM_LINEAR_FEET,
    UOM_LINEAR_YARDS,
    UOM_SQUARE_FEET,
)

_REF_818_OLD_LENGTHS = (9.2, 2.1, 3.4, 2.7, 1.0, 919.6)
_REF_818_NEW_LENGTHS = tuple(reversed(_REF_818_OLD_LENGTHS))


def _condition(uid: str, ref_no: int, name: str = "Condition", notes: str = ""):
    return Condition(
        uid=uid,
        ref_no=ref_no,
        name=name,
        notes=notes,
        cdn_type_name="Type A",
        condition_type=Condition.TYPE_LINEAR,
        calc_type1=1,
        calc_type2=3,
        calc_type3=20,
        uom1=UOM_LINEAR_FEET,
        uom2=UOM_SQUARE_FEET,
        uom3=UOM_CUBIC_YARDS,
        height=12.0,
        width=12.0,
        depth=12.0,
        thickness=12.0,
    )


def _takeoff(uid: str, condition_uid: str, page_uid: str, length: float = 12.0):
    return Takeoff(
        uid=uid,
        condition_uid=condition_uid,
        page_uid=page_uid,
        position=[0.0, 0.0, length, 0.0],
    )


def _bid_data(conditions, takeoffs, page_prefix: str):
    pages = {
        f"{page_prefix}-a": Page(uid=f"{page_prefix}-a", name="A.pdf"),
        f"{page_prefix}-b": Page(uid=f"{page_prefix}-b", name="B.pdf"),
        f"{page_prefix}-c": Page(uid=f"{page_prefix}-c", name="C.pdf"),
    }
    return BidLoadResult(
        bid_conditions={condition.uid: condition for condition in conditions},
        bid_takeoffs=takeoffs,
        pages=pages,
    )


class BidComparisonServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = BidComparisonService()

    def _comparison(self, include_details=False):
        old_conditions = [
            _condition("old-1", 1, "Unchanged"),
            _condition("old-2", 2, "Quantity"),
            _condition("old-3", 3, "Metadata", notes="old note"),
            _condition("old-4", 4, "Page distribution"),
            _condition("old-6", 6, "Removed"),
        ]
        new_conditions = [
            _condition("new-1", 1, "Unchanged"),
            _condition("new-2", 2, "Quantity"),
            _condition("new-3", 3, "Metadata", notes="new note"),
            _condition("new-4", 4, "Page distribution"),
            _condition("new-5", 5, "Added"),
        ]
        old_takeoffs = [
            _takeoff("old-t1", "old-1", "old-a"),
            _takeoff("old-t2", "old-2", "old-a"),
            _takeoff("old-t4", "old-4", "old-a"),
            _takeoff("old-t6a", "old-6", "old-c"),
            _takeoff("old-t6b", "old-6", "old-c"),
            _takeoff("old-t6c", "old-6", "old-c"),
        ]
        new_takeoffs = [
            _takeoff("new-t1", "new-1", "new-a"),
            _takeoff("new-t2", "new-2", "new-a", length=24.0),
            _takeoff("new-t4", "new-4", "new-b"),
            _takeoff("new-t5a", "new-5", "new-c"),
            _takeoff("new-t5b", "new-5", "new-c"),
        ]
        return self.service.compare(
            old_bid=McpBidDto(
                uid="old", name="Old Bid", condition_count=5, page_count=3
            ),
            new_bid=McpBidDto(
                uid="new", name="New Bid", condition_count=5, page_count=3
            ),
            old_data=_bid_data(old_conditions, old_takeoffs, "old"),
            new_data=_bid_data(new_conditions, new_takeoffs, "new"),
            limit=MCP_BID_COMPARISON_DEFAULT_LIMIT,
            include_details=include_details,
        )

    def _compare_takeoff_lengths(self, old_lengths, new_lengths):
        old_condition = _condition("old", 1)
        new_condition = _condition("new", 1)
        return self.service.compare(
            old_bid=McpBidDto(uid="old", name="Old"),
            new_bid=McpBidDto(uid="new", name="New"),
            old_data=_bid_data(
                [old_condition],
                [
                    _takeoff(f"old-{index}", "old", "old-a", length)
                    for index, length in enumerate(old_lengths)
                ],
                "old",
            ),
            new_data=_bid_data(
                [new_condition],
                [
                    _takeoff(f"new-{index}", "new", "new-a", length)
                    for index, length in enumerate(new_lengths)
                ],
                "new",
            ),
            limit=MCP_BID_COMPARISON_DEFAULT_LIMIT,
            include_details=True,
        )

    def test_classifies_unchanged_changed_added_and_removed_by_ref_no(self):
        result = self._comparison(include_details=True)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.data.counts.unchanged, 1)
        self.assertEqual(result.data.counts.changed, 3)
        self.assertEqual(result.data.counts.added, 1)
        self.assertEqual(result.data.counts.removed, 1)
        details = {detail.ref_no: detail for detail in result.data.details}
        self.assertNotIn(1, details)
        self.assertEqual(details[2].classification, "changed")
        self.assertTrue(details[2].quantity_changed)
        self.assertFalse(details[2].metadata_changed)
        self.assertFalse(details[2].takeoff_count_changed)
        self.assertFalse(details[2].page_distribution_changed)
        self.assertTrue(details[3].metadata_changed)
        self.assertFalse(details[3].quantity_changed)
        self.assertTrue(details[4].page_distribution_changed)
        self.assertFalse(details[4].quantity_changed)
        self.assertEqual(details[5].classification, "added")
        self.assertEqual(details[6].classification, "removed")

    def test_aggregates_only_by_type_with_quantities_counts_and_page_names(self):
        result = self._comparison()
        self.assertEqual(len(result.data.groups), 1)
        group = result.data.groups[0]
        self.assertEqual(group.cdn_type_name, "Type A")
        self.assertEqual(group.total_affected, 5)
        self.assertEqual((group.changed, group.added, group.removed), (3, 1, 1))
        self.assertEqual(group.qty1.uom_label, "LF")
        self.assertEqual(group.qty2.uom_label, "SF")
        self.assertEqual(group.qty3.uom_label, "CY")
        self.assertAlmostEqual(group.qty1.old, 5.0)
        self.assertAlmostEqual(group.qty1.new, 5.0)
        self.assertAlmostEqual(group.qty2.old, 5.0)
        self.assertAlmostEqual(group.qty2.new, 5.0)
        self.assertAlmostEqual(group.qty3.old, 5.0 / 27.0)
        self.assertAlmostEqual(group.qty3.new, 5.0 / 27.0)
        self.assertEqual(group.takeoffs, {"old": 5, "new": 4})
        self.assertEqual(group.compact_page_changes, ["A.pdf", "B.pdf", "C.pdf"])
        self.assertFalse(
            any(name.startswith(("+", "-")) for name in group.compact_page_changes)
        )
        self.assertEqual(result.data.details, [])
        self.assertFalse(result.meta.details_included)

    def test_reports_top_level_bid_metadata_changes(self):
        result = self._comparison()
        self.assertTrue(result.data.bid_metadata_changed)
        changes = {change.field: change for change in result.data.bid_metadata_changes}
        self.assertEqual(changes["name"].old, "Old Bid")
        self.assertEqual(changes["name"].new, "New Bid")
        self.assertNotIn("uid", changes)
        self.assertNotIn("selected_page_uid", changes)

    def test_duplicate_ref_no_aborts_matching_with_structured_warning(self):
        old_conditions = [
            _condition("old-a", 7, "First"),
            _condition("old-b", 7, "Second"),
        ]
        result = self.service.compare(
            old_bid=McpBidDto(uid="old", name="Old"),
            new_bid=McpBidDto(uid="new", name="New"),
            old_data=_bid_data(old_conditions, [], "old"),
            new_data=_bid_data([_condition("new-a", 7)], [], "new"),
            limit=MCP_BID_COMPARISON_DEFAULT_LIMIT,
        )
        self.assertEqual(result.status, MCP_STATUS_DUPLICATE_REF_NO)
        self.assertEqual(result.data.groups, [])
        self.assertEqual(result.data.duplicate_ref_nos[0].bid, "old")
        self.assertEqual(result.data.duplicate_ref_nos[0].ref_no, 7)
        self.assertEqual(result.data.duplicate_ref_nos[0].condition_count, 2)
        self.assertIn("comparison was not performed", result.data.warnings[0])

    def test_zero_ref_no_is_matched_directly_without_uid_or_name_fallback(self):
        result = self.service.compare(
            old_bid=McpBidDto(uid="old", name="Old"),
            new_bid=McpBidDto(uid="new", name="New"),
            old_data=_bid_data([_condition("old-zero", 0, "Old name")], [], "old"),
            new_data=_bid_data([_condition("new-zero", 0, "New name")], [], "new"),
            limit=MCP_BID_COMPARISON_DEFAULT_LIMIT,
            include_details=True,
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.data.counts.changed, 1)
        self.assertEqual(result.data.details[0].ref_no, 0)
        self.assertTrue(result.data.details[0].metadata_changed)

    def test_duplicate_zero_ref_no_is_detected_on_each_bid_independently(self):
        result = self.service.compare(
            old_bid=McpBidDto(uid="old", name="Old"),
            new_bid=McpBidDto(uid="new", name="New"),
            old_data=_bid_data(
                [_condition("old-a", 0), _condition("old-b", 0)], [], "old"
            ),
            new_data=_bid_data(
                [_condition("new-a", 0), _condition("new-b", 0)], [], "new"
            ),
            limit=MCP_BID_COMPARISON_DEFAULT_LIMIT,
        )
        self.assertEqual(result.status, MCP_STATUS_DUPLICATE_REF_NO)
        self.assertEqual(
            {
                (duplicate.bid, duplicate.ref_no)
                for duplicate in result.data.duplicate_ref_nos
            },
            {("old", 0), ("new", 0)},
        )
        self.assertEqual(len(result.data.warnings), 2)

    def test_visibility_change_is_reported_without_changing_page_distribution(self):
        old_condition = _condition("old", 1)
        new_condition = _condition("new", 1)
        new_condition.layer_visible = False
        result = self.service.compare(
            old_bid=McpBidDto(uid="old", name="Old"),
            new_bid=McpBidDto(uid="new", name="New"),
            old_data=_bid_data(
                [old_condition], [_takeoff("old-t", "old", "old-a")], "old"
            ),
            new_data=_bid_data(
                [new_condition], [_takeoff("new-t", "new", "new-a")], "new"
            ),
            limit=MCP_BID_COMPARISON_DEFAULT_LIMIT,
            include_details=True,
        )
        detail = result.data.details[0]
        self.assertTrue(detail.visible_takeoff_count_changed)
        self.assertTrue(detail.metadata_changed)
        self.assertTrue(detail.quantity_changed)
        self.assertFalse(detail.page_distribution_changed)

    def test_mixed_uom_warning_uses_target_label(self):
        old_condition = _condition("old", 1)
        new_condition = _condition("new", 1)
        new_condition.uom1 = UOM_LINEAR_YARDS
        result = self.service.compare(
            old_bid=McpBidDto(uid="old", name="Old"),
            new_bid=McpBidDto(uid="new", name="New"),
            old_data=_bid_data(
                [old_condition], [_takeoff("old-t", "old", "old-a")], "old"
            ),
            new_data=_bid_data(
                [new_condition], [_takeoff("new-t", "new", "new-a")], "new"
            ),
            limit=MCP_BID_COMPARISON_DEFAULT_LIMIT,
        )
        self.assertEqual(result.data.groups[0].qty1.uom_label, "LY")
        self.assertEqual(
            result.data.warnings,
            ["Type A qty1 contains mixed UOM labels: LF, LY; reporting LY."],
        )

    def test_tiny_quantity_float_noise_is_unchanged(self):
        old_total = sum(length / 12.0 for length in _REF_818_OLD_LENGTHS)
        new_total = sum(length / 12.0 for length in _REF_818_NEW_LENGTHS)
        self.assertEqual(old_total, 78.16666666666667)
        self.assertEqual(new_total, 78.16666666666666)
        result = self._compare_takeoff_lengths(
            _REF_818_OLD_LENGTHS, _REF_818_NEW_LENGTHS
        )
        self.assertEqual(result.data.counts.unchanged, 1)
        self.assertEqual(result.data.counts.changed, 0)
        self.assertEqual(result.data.details, [])

    def test_meaningful_quantity_difference_is_changed(self):
        result = self._compare_takeoff_lengths([12.0], [12.01])
        self.assertEqual(result.data.counts.unchanged, 0)
        self.assertEqual(result.data.counts.changed, 1)
        self.assertTrue(result.data.details[0].quantity_changed)

    def test_bid_38647_to_36969_repro_has_expected_classification_counts(self):
        unchanged_refs = list(range(1, 782)) + [818]
        changed_refs = list(range(783, 795))
        removed_refs = list(range(795, 802))
        added_ref = 802
        old_conditions = [
            _condition(
                f"old-{ref_no}",
                ref_no,
                (
                    "BA - To 4' Wall - Stem, Short or Pit Wall"
                    if ref_no == 818
                    else f"Condition {ref_no}"
                ),
            )
            for ref_no in unchanged_refs
        ]
        new_conditions = [
            _condition(
                f"new-{ref_no}",
                ref_no,
                (
                    "BA - To 4' Wall - Stem, Short or Pit Wall"
                    if ref_no == 818
                    else f"Condition {ref_no}"
                ),
            )
            for ref_no in unchanged_refs
        ]
        old_conditions.extend(
            _condition(f"old-{ref_no}", ref_no, notes="old") for ref_no in changed_refs
        )
        new_conditions.extend(
            _condition(f"new-{ref_no}", ref_no, notes="new") for ref_no in changed_refs
        )
        old_conditions.extend(
            _condition(f"old-{ref_no}", ref_no) for ref_no in removed_refs
        )
        new_conditions.append(_condition(f"new-{added_ref}", added_ref))
        result = self.service.compare(
            old_bid=McpBidDto(uid="38647", name="Bid 36", bid_no=36),
            new_bid=McpBidDto(uid="36969", name="Bid 35", bid_no=35),
            old_data=_bid_data(
                old_conditions,
                [
                    _takeoff(f"old-818-{index}", "old-818", "old-a", length)
                    for index, length in enumerate(_REF_818_OLD_LENGTHS)
                ],
                "old",
            ),
            new_data=_bid_data(
                new_conditions,
                [
                    _takeoff(f"new-818-{index}", "new-818", "new-a", length)
                    for index, length in enumerate(_REF_818_NEW_LENGTHS)
                ],
                "new",
            ),
            limit=5000,
            include_details=True,
        )
        counts = result.data.counts
        self.assertEqual(
            (counts.unchanged, counts.changed, counts.added, counts.removed),
            (782, 12, 1, 7),
        )
        self.assertNotIn(818, {detail.ref_no for detail in result.data.details})

    def test_details_and_groups_are_bounded_independently(self):
        result = self._comparison(include_details=True)
        limited = self.service.compare(
            result.data.old_bid,
            result.data.new_bid,
            _bid_data([_condition("old-1", 1)], [], "old"),
            _bid_data([_condition("new-2", 2), _condition("new-3", 3)], [], "new"),
            include_details=True,
            limit=1,
        )
        self.assertEqual(limited.meta.returned_count, 1)
        self.assertEqual(limited.meta.detail_returned_count, 1)
        self.assertEqual(limited.meta.detail_total_count, 3)
        self.assertTrue(limited.meta.details_truncated)


if __name__ == "__main__":
    unittest.main()
