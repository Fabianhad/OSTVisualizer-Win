import unittest
from ost_visualizer.application.services.mcp_read_service import (
    McpDatabaseRef,
    McpReadError,
    McpReadService,
)
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.file_results import BidLoadResult, FileLoadResult
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.uom_service import CALC_COUNT, UOM_EACH


class FakeProjectRepository:
    def __init__(self):
        self.file_path = "demo.mdb"
        self.hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path=self.file_path,
                    display_name="Demo",
                    bid_projects={
                        "project-1": HierarchyProjectInfo(
                            name="Project One",
                            bids=[
                                HierarchyBidInfo(
                                    uid="bid-1",
                                    name="Bid One",
                                    page_count=2,
                                    condition_count=2,
                                )
                            ],
                        )
                    },
                )
            ]
        )
        visible = Condition(
            uid="cond-1",
            name="Visible Count",
            condition_type=Condition.TYPE_COUNT,
            calc_type1=CALC_COUNT,
            uom1=UOM_EACH,
            ref_no=1,
        )
        hidden = Condition(
            uid="cond-2",
            name="Hidden Count",
            condition_type=Condition.TYPE_COUNT,
            calc_type1=CALC_COUNT,
            uom1=UOM_EACH,
            ref_no=2,
            layer_visible=False,
        )
        unused = Condition(
            uid="cond-3",
            name="Unused Linear",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=3,
        )
        page1 = Page(uid="page-1", name="A101", image_path="A101.pdf", page_index=0)
        page2 = Page(uid="page-2", name="A102", image_path="A102.pdf", page_index=1)
        page3 = Page(uid="page-3", name="A103", image_path="A103.pdf", page_index=2)
        t1 = Takeoff(
            uid="takeoff-1",
            condition_uid="cond-1",
            page_uid="page-1",
            area_uid="area-1",
            position=[1.0, 2.0],
        )
        t2 = Takeoff(
            uid="takeoff-2",
            condition_uid="cond-1",
            page_uid="page-1",
            area_uid="area-1",
            position=[3.0, 4.0],
        )
        t3 = Takeoff(
            uid="takeoff-hidden",
            condition_uid="cond-2",
            page_uid="page-2",
            area_uid="0",
            position=[5.0, 6.0],
        )
        page1.takeoffs = [t1, t2]
        page2.takeoffs = [t3]
        self.bid_data = BidLoadResult(
            bid_conditions={"cond-1": visible, "cond-2": hidden, "cond-3": unused},
            bid_takeoffs=[t1, t2, t3],
            bid_areas={
                "area-1": BidArea(
                    uid="area-1",
                    bid_uid="bid-1",
                    parent_uid="",
                    name="Level One Deck",
                    sequence=1,
                    guid="{AREA-1}",
                ),
                "area-2": BidArea(
                    uid="area-2",
                    bid_uid="bid-1",
                    parent_uid="area-1",
                    name="Nested Area",
                    sequence=2,
                    guid="{AREA-2}",
                ),
            },
            pages={"page-1": page1, "page-2": page2, "page-3": page3},
            selected_page_uid="page-2",
        )

    def load_file(self, file_path):
        return FileLoadResult(success=True, hierarchy=self.hierarchy)

    def load_bid(self, bid_uid, file_path=None):
        return self.bid_data if bid_uid == "bid-1" else BidLoadResult()


class McpReadServiceTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeProjectRepository()
        self.service = McpReadService(
            self.repo,
            [
                McpDatabaseRef(
                    database_id="db-1",
                    file_path=self.repo.file_path,
                    display_name="Demo",
                )
            ],
        )

    def test_lists_projects_and_bids(self):
        projects = self.service.list_projects("db-1")
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].uid, "project-1")
        bids = self.service.list_bids("db-1")
        self.assertEqual(len(bids), 1)
        self.assertEqual(bids[0].uid, "bid-1")

    def test_hierarchy_lookup_does_not_fall_back_to_unmatched_file(self):
        self.repo.hierarchy.loaded_files[0].file_path = "other.mdb"
        with self.assertRaises(McpReadError):
            self.service.list_projects("db-1")

    def test_current_page_uses_saved_bid_selected_page(self):
        page = self.service.get_current_page("db-1", "bid-1")
        self.assertIsNotNone(page)
        self.assertEqual(page.uid, "page-2")
        self.assertTrue(page.is_pdf)

    def test_list_takeoffs_filters_visible_and_limit(self):
        takeoffs = self.service.list_takeoffs("db-1", "bid-1", limit=1)
        self.assertEqual([t.uid for t in takeoffs], ["takeoff-1"])
        self.assertEqual(takeoffs[0].area_name, "Level One Deck")
        all_takeoffs = self.service.list_takeoffs("db-1", "bid-1", visible_only=False)
        self.assertEqual(len(all_takeoffs), 3)
        self.assertIsNone(all_takeoffs[2].area_name)

    def test_area_tools_report_metadata_and_usage(self):
        areas = self.service.list_areas("db-1", "bid-1")
        self.assertEqual([area.uid for area in areas], ["area-1", "area-2"])
        self.assertEqual(areas[0].name, "Level One Deck")
        self.assertEqual(areas[0].guid, "{AREA-1}")
        self.assertEqual(areas[0].child_uids, ["area-2"])
        self.assertEqual(areas[0].takeoff_count, 2)
        self.assertEqual(areas[0].visible_takeoff_count, 2)
        self.assertEqual(areas[0].page_count, 1)
        summary = self.service.get_area_summary("db-1", "bid-1", "area-1")
        self.assertEqual(summary.status, "ok")
        self.assertEqual(summary.area.name, "Level One Deck")
        self.assertEqual([page.page_uid for page in summary.pages], ["page-1"])
        self.assertEqual([child.uid for child in summary.children], ["area-2"])

    def test_unassigned_area_summary_uses_clear_synthetic_metadata(self):
        summary = self.service.get_area_summary("db-1", "bid-1", "0")
        self.assertEqual(summary.area.uid, "0")
        self.assertEqual(summary.area.name, "Unassigned")
        self.assertEqual(summary.area.takeoff_count, 1)
        self.assertEqual([page.page_uid for page in summary.pages], ["page-2"])

    def test_quantity_summary_reuses_domain_quantity_logic(self):
        quantities = self.service.get_page_quantity_summary("db-1", "bid-1", "page-1")
        self.assertEqual(len(quantities), 1)
        self.assertEqual(quantities[0].condition_uid, "cond-1")
        self.assertEqual(quantities[0].quantity1, 2.0)
        self.assertEqual(quantities[0].uom1_label, "EA")

    def test_search_takeoffs_uses_narrow_text_fields(self):
        matches = self.service.search_takeoffs("db-1", "bid-1", "visible")
        self.assertEqual([m.uid for m in matches], ["takeoff-1", "takeoff-2"])
        by_area_name = self.service.search_takeoffs("db-1", "bid-1", "deck")
        self.assertEqual([m.uid for m in by_area_name], ["takeoff-1", "takeoff-2"])
        filtered = self.service.search_takeoffs(
            "db-1", "bid-1", "visible", condition_uid="cond-1", limit=1
        )
        self.assertEqual([m.uid for m in filtered], ["takeoff-1"])

    def test_search_conditions_is_bounded(self):
        matches = self.service.search_conditions("db-1", "bid-1", "count", limit=1)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].uid, "cond-1")

    def test_condition_summary_includes_pages_and_quantities(self):
        summary = self.service.get_condition_summary("db-1", "bid-1", "cond-1")
        self.assertEqual(summary.condition.uid, "cond-1")
        self.assertEqual(summary.takeoff_count, 2)
        self.assertEqual(summary.visible_takeoff_count, 2)
        self.assertEqual(summary.pages[0].page_uid, "page-1")
        self.assertEqual(summary.quantities[0].quantity1, 2.0)

    def test_selected_takeoffs_summary_uses_selected_ids(self):
        summary = self.service.get_selected_takeoffs_summary(
            "db-1", "bid-1", ["takeoff-2", "missing"]
        )
        self.assertEqual(summary.status, "ok")
        self.assertEqual(summary.selected_takeoff_count, 1)
        self.assertEqual(summary.missing_takeoff_uids, ["missing"])
        self.assertEqual(summary.takeoffs[0].uid, "takeoff-2")
        self.assertEqual(summary.takeoffs[0].area_name, "Level One Deck")
        self.assertEqual(summary.pages[0].page_uid, "page-1")

    def test_selected_takeoffs_summary_handles_no_selection(self):
        summary = self.service.get_selected_takeoffs_summary("db-1", "bid-1", [])
        self.assertEqual(summary.status, "no_selection")

    def test_selected_pages_summary_preserves_multi_page_selection_order(self):
        summary = self.service.get_selected_pages_summary(
            "db-1",
            "bid-1",
            ["page-2", "page-1", "missing"],
            active_view="3d",
            active_page_uid="page-1",
        )
        self.assertEqual(summary.status, "ok")
        self.assertEqual(summary.active_view, "3d")
        self.assertEqual(summary.active_page_uid, "page-1")
        self.assertEqual(summary.selected_page_uids, ["page-2", "page-1"])
        self.assertEqual(summary.missing_page_uids, ["missing"])
        self.assertEqual([page.uid for page in summary.pages], ["page-2", "page-1"])

    def test_consistency_checks_find_unused_pages_and_conditions(self):
        pages = self.service.find_pages_without_takeoffs("db-1", "bid-1")
        self.assertEqual([page.uid for page in pages], ["page-3"])
        conditions = self.service.find_conditions_without_takeoffs("db-1", "bid-1")
        self.assertEqual([condition.uid for condition in conditions], ["cond-3"])

    def test_bid_quantity_summary_has_stable_shape_and_limit_metadata(self):
        summary = self.service.get_bid_quantity_summary("db-1", "bid-1", limit=2)
        self.assertEqual(summary.status, "truncated")
        self.assertEqual(summary.meta.limit, 2)
        self.assertEqual(summary.meta.returned_count, 2)
        self.assertEqual(summary.meta.total_count, 3)
        first = summary.conditions[0]
        self.assertEqual(first.condition.uid, "cond-1")
        self.assertEqual(first.page_count, 1)
        self.assertFalse(first.zero_quantity)

    def test_summary_limits_are_clamped_and_report_exact_counts(self):
        summary = self.service.get_bid_quantity_summary("db-1", "bid-1", limit=0)
        self.assertEqual(summary.status, "truncated")
        self.assertEqual(summary.meta.limit, 1)
        self.assertEqual(summary.meta.returned_count, 1)
        self.assertEqual(summary.meta.total_count, 3)
        self.assertTrue(summary.meta.truncated)
        empty = self.service.find_duplicate_conditions("db-1", "bid-1", limit=99999)
        self.assertEqual(empty.status, "empty")
        self.assertEqual(empty.meta.limit, 5000)
        self.assertEqual(empty.meta.returned_count, 0)
        self.assertEqual(empty.meta.total_count, 0)
        self.assertFalse(empty.meta.truncated)

    def test_scope_duplicate_zero_unplaced_and_page_context_checks(self):
        duplicate = Condition(uid="cond-4", name="Visible Count", ref_no=4)
        self.repo.bid_data.bid_conditions[duplicate.uid] = duplicate
        unplaced = Takeoff(uid="unplaced-1", condition_uid="cond-1", page_uid="")
        self.repo.bid_data.bid_takeoffs.append(unplaced)
        gaps = self.service.review_scope_gaps("db-1", "bid-1")
        self.assertEqual(gaps.status, "ok")
        self.assertEqual(gaps.meta.total_count, 4)
        self.assertEqual(gaps.meta.returned_count, 4)
        self.assertEqual([page.uid for page in gaps.pages_without_takeoffs], ["page-3"])
        self.assertEqual([t.uid for t in gaps.takeoffs_missing_pages], ["unplaced-1"])
        duplicates = self.service.find_duplicate_conditions("db-1", "bid-1")
        self.assertEqual(duplicates.status, "ok")
        self.assertEqual(duplicates.groups[0].name, "Visible Count")
        self.assertEqual(
            [condition.uid for condition in duplicates.groups[0].conditions],
            ["cond-1", "cond-4"],
        )
        zero = self.service.find_zero_quantity_conditions("db-1", "bid-1")
        self.assertEqual([item.condition.uid for item in zero.conditions], ["cond-2"])
        unplaced_summary = self.service.find_unplaced_takeoffs("db-1", "bid-1")
        self.assertEqual(
            [takeoff.uid for takeoff in unplaced_summary.takeoffs],
            ["unplaced-1"],
        )
        page_context = self.service.get_page_context("db-1", "bid-1", "page-1")
        self.assertEqual(page_context.status, "ok")
        self.assertEqual(page_context.page_label, "A101")
        self.assertEqual(page_context.source_file_name, "A101.pdf")
        self.assertTrue(page_context.has_pdf_source)
        self.assertEqual(page_context.page_text_status, "deferred")

    def test_rejects_unknown_database_and_filter_ids(self):
        with self.assertRaises(McpReadError):
            self.service.list_projects("missing")
        with self.assertRaises(McpReadError):
            self.service.list_takeoffs("db-1", "bid-1", page_uid="missing")
        with self.assertRaises(McpReadError):
            self.service.list_takeoffs("db-1", "bid-1", condition_uid="missing")


if __name__ == "__main__":
    unittest.main()
