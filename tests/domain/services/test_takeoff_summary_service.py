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
