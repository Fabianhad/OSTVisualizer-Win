import unittest
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.takeoff_summary_service import (
    summarize_takeoffs_by_page,
)


class SummarizeTakeoffsByPageTests(unittest.TestCase):
    def test_totals_include_hidden_items_but_visible_counts_follow_conditions(self):
        conditions = {"hidden": Condition(uid="hidden", layer_visible=False)}
        pages = {"p": Page(uid="p", name="Page", page_index=1)}
        takeoffs = [
            Takeoff(uid="hidden", page_uid="p", condition_uid="hidden"),
            Takeoff(uid="missing", page_uid="p", condition_uid="unresolved"),
        ]
        summary = summarize_takeoffs_by_page(takeoffs, pages, conditions)
        self.assertEqual(len(summary), 1)
        self.assertEqual((summary[0].page_uid, summary[0].page_name), ("p", "Page"))
        self.assertEqual(
            (summary[0].takeoff_count, summary[0].visible_takeoff_count), (2, 1)
        )

    def test_missing_page_and_ties_have_deterministic_order_without_empty_pages(self):
        pages = {
            "b": Page(uid="b", name="Same", page_index=1),
            "a": Page(uid="a", name="same", page_index=1),
            "empty": Page(uid="empty", name="Empty"),
        }
        takeoffs = [
            Takeoff(uid=uid, page_uid=uid, condition_uid="")
            for uid in ("b", "a", "missing")
        ]
        summary = summarize_takeoffs_by_page(takeoffs, pages, {})
        self.assertEqual([item.page_uid for item in summary], ["missing", "a", "b"])
        self.assertEqual(summary[0].page_name, "")
        self.assertEqual(summarize_takeoffs_by_page([], pages, {}), [])


class PageTakeoffSummaryContractTests(unittest.TestCase):
    def test_summary_defaults_are_zero_counts_and_it_is_frozen(self):
        from dataclasses import FrozenInstanceError
        from ost_visualizer.domain.services.takeoff_summary_service import (
            PageTakeoffSummary,
        )

        summary = PageTakeoffSummary("p", "Page")
        self.assertEqual((summary.takeoff_count, summary.visible_takeoff_count), (0, 0))
        with self.assertRaises(FrozenInstanceError):
            summary.takeoff_count = 1

    def test_a_page_whose_takeoffs_are_all_hidden_reports_zero_visible(self):
        conditions = {"h": Condition(uid="h", layer_visible=False)}
        pages = {"p": Page(uid="p", name="Page")}
        takeoffs = [Takeoff(uid=str(i), page_uid="p", condition_uid="h") for i in range(3)]
        (summary,) = summarize_takeoffs_by_page(takeoffs, pages, conditions)
        self.assertEqual((summary.takeoff_count, summary.visible_takeoff_count), (3, 0))

    def test_counts_are_kept_per_page_and_mixed_visibility_is_split(self):
        conditions = {
            "h": Condition(uid="h", layer_visible=False),
            "v": Condition(uid="v", layer_visible=True),
        }
        pages = {"a": Page(uid="a", name="A"), "b": Page(uid="b", name="B", page_index=1)}
        takeoffs = [
            Takeoff(uid="1", page_uid="a", condition_uid="v"),
            Takeoff(uid="2", page_uid="a", condition_uid="h"),
            Takeoff(uid="3", page_uid="b", condition_uid="v"),
            Takeoff(uid="4", page_uid="a", condition_uid="v"),
        ]
        summary = {s.page_uid: s for s in summarize_takeoffs_by_page(takeoffs, pages, conditions)}
        self.assertEqual(
            (summary["a"].takeoff_count, summary["a"].visible_takeoff_count), (3, 2)
        )
        self.assertEqual(
            (summary["b"].takeoff_count, summary["b"].visible_takeoff_count), (1, 1)
        )

    def test_pages_sort_by_page_index_then_case_insensitive_name_with_unknown_pages_at_index_zero(self):
        pages = {
            "late": Page(uid="late", name="Alpha", page_index=5),
            "early": Page(uid="early", name="Zulu", page_index=2),
            "mid": Page(uid="mid", name="beta", page_index=2),
            "zed": Page(uid="zed", name="Zed", page_index=0),
        }
        takeoffs = [
            Takeoff(uid=uid, page_uid=uid, condition_uid="")
            for uid in ("late", "early", "mid", "ghost", "zed")
        ]
        order = [s.page_uid for s in summarize_takeoffs_by_page(takeoffs, pages, {})]
        self.assertEqual(order, ["ghost", "zed", "mid", "early", "late"])
