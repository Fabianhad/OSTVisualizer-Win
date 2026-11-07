import unittest
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.services.page_selection_service import PageSelectionService


class PageSelectionAnnotationIdentityTests(unittest.TestCase):
    def test_in_memory_annotation_add_replaces_existing_uid(self):
        service = PageSelectionService()
        service.set_annotations(
            [
                BidAnnotation(
                    uid="a1",
                    annotation_type="rect",
                    page_uid="p1",
                    position=[1.0, 1.0],
                ),
                BidAnnotation(
                    uid="a1",
                    annotation_type="oval",
                    page_uid="p1",
                    position=[4.0, 4.0],
                ),
                BidAnnotation(
                    uid="a2",
                    annotation_type="oval",
                    page_uid="p1",
                    position=[2.0, 2.0],
                ),
            ]
        )
        service.add_annotations(
            [
                BidAnnotation(
                    uid="a1",
                    annotation_type="rect",
                    page_uid="p2",
                    position=[3.0, 3.0],
                )
            ]
        )
        annotations = service.get_all_annotations()
        self.assertEqual(
            [(a.uid, a.annotation_type) for a in annotations],
            [("a1", "oval"), ("a2", "oval"), ("a1", "rect")],
        )
        self.assertEqual(annotations[0].page_uid, "p1")
        self.assertEqual(annotations[0].position, [4.0, 4.0])
        self.assertEqual(annotations[-1].page_uid, "p2")
        self.assertEqual(annotations[-1].position, [3.0, 3.0])

    def test_in_memory_annotation_remove_by_key_preserves_same_uid_other_type(self):
        service = PageSelectionService()
        service.set_annotations(
            [
                BidAnnotation(uid="a1", annotation_type="rect", page_uid="p1"),
                BidAnnotation(uid="a1", annotation_type="oval", page_uid="p2"),
            ]
        )
        page_uids = service.remove_annotations_by_keys([("a1", "rect")])
        self.assertEqual(page_uids, ["p1"])
        self.assertEqual(
            [
                (a.uid, a.annotation_type, a.page_uid)
                for a in service.get_all_annotations()
            ],
            [("a1", "oval", "p2")],
        )

    def test_page_replacement_prunes_selection_and_copies_caller_container(self):
        service = PageSelectionService()
        original = Page(uid="p1", name="Original")
        service.set_pages({"p1": original, "p2": Page(uid="p2", name="Other")})
        selected = service.select_pages(["p2", "p1", "p2", ""])
        self.assertEqual(selected, ["p2", "p1"])
        selected.clear()
        self.assertEqual(service.get_selected_pages(), ["p2", "p1"])
        replacement = Page(uid="p1", name="Replacement")
        pages = {"p1": replacement}
        service.set_pages(pages)
        pages.clear()
        self.assertEqual(service.get_selected_pages(), ["p1"])
        self.assertIs(service.get_page("p1"), replacement)
        self.assertIsNone(service.get_page("p2"))
        service.clear()
        self.assertEqual(service.get_selected_pages(), [])
        self.assertIsNone(service.get_page("p1"))


class PageSelectionQueryTests(unittest.TestCase):
    def setUp(self):
        from ost_visualizer.domain.entities.takeoff import Takeoff

        self.t1 = Takeoff(uid="t1", condition_uid="c", page_uid="p1")
        self.t2 = Takeoff(uid="t2", condition_uid="c", page_uid="p1")
        self.t3 = Takeoff(uid="t3", condition_uid="c", page_uid="p2")
        self.p1 = Page(uid="p1", name="Sheet One", takeoffs=[self.t1, self.t2])
        self.p2 = Page(uid="p2", name="Sheet Two", takeoffs=[self.t3])
        self.p3 = Page(uid="p3", name="Empty")
        self.service = PageSelectionService()
        self.service.set_pages({"p1": self.p1, "p2": self.p2, "p3": self.p3})

    def test_page_names_distinguish_the_no_page_bucket_unknown_and_known_pages(self):
        self.assertEqual(self.service.get_page_name("NO_PAGE_ID"), "Items Without Page")
        self.assertEqual(self.service.get_page_name("p1"), "Sheet One")
        self.assertEqual(self.service.get_page_name("zzz"), "Page zzz")
        self.assertEqual(self.service.get_page_name(""), "Page ")

    def test_takeoffs_are_returned_per_page_for_all_pages_and_for_the_selection(self):
        self.assertIs(self.service.get_page_takeoffs("p1"), self.p1.takeoffs)
        self.assertEqual(self.service.get_page_takeoffs("missing"), [])
        self.assertEqual(self.service.get_all_takeoffs(), [self.t1, self.t2, self.t3])
        self.assertEqual(self.service.get_all_selected_takeoffs(), [])
        self.service.select_pages(["p2", "p1", "p3", "ghost"])
        self.assertEqual(
            self.service.get_all_selected_takeoffs(), [self.t3, self.t1, self.t2]
        )
        # The aggregate list is a copy; the page's own list is not extended.
        self.service.get_all_takeoffs().append(self.t3)
        self.assertEqual(len(self.p1.takeoffs), 2)

    def test_has_takeoffs_for_pages_is_true_only_when_one_listed_page_has_takeoffs(
        self,
    ):
        self.assertIs(self.service.has_takeoffs_for_pages(["p3", "ghost"]), False)
        self.assertIs(self.service.has_takeoffs_for_pages(["p3", "p2"]), True)
        self.assertIs(self.service.has_takeoffs_for_pages([]), False)
        self.assertIs(self.service.has_takeoffs_for_pages(iter(["p1"])), True)

    def test_selection_deduplicates_drops_blank_uids_and_can_be_cleared(self):
        self.assertEqual(
            self.service.select_pages(["", None, "p1", "p1", "p2"]), ["p1", "p2"]
        )
        self.service.clear_selection()
        self.assertEqual(self.service.get_selected_pages(), [])
        self.assertEqual(self.service.select_pages([]), [])
        returned = self.service.select_pages(iter(["p3"]))
        returned.append("x")
        self.assertEqual(self.service.get_selected_pages(), ["p3"])

    def test_selection_survives_pruning_only_for_pages_that_still_exist(self):
        self.service.select_pages(["p1", "p2", "ghost"])
        self.service.set_pages({"p2": self.p2})
        self.assertEqual(self.service.get_selected_pages(), ["p2"])

    def test_clear_removes_pages_selection_and_annotations(self):
        self.service.select_pages(["p1"])
        self.service.set_annotations(
            [BidAnnotation(uid="a", annotation_type="rect", page_uid="p1")]
        )
        self.service.clear()
        self.assertEqual(
            (
                self.service.get_all_takeoffs(),
                self.service.get_selected_pages(),
                self.service.get_all_annotations(),
                self.service.get_page_annotations("p1"),
            ),
            ([], [], [], []),
        )


class PageSelectionAnnotationCollectionTests(unittest.TestCase):
    def annotations(self):
        return [
            BidAnnotation(uid="a1", annotation_type="rect", page_uid="p1"),
            BidAnnotation(uid="a2", annotation_type="rect", page_uid="p1"),
            BidAnnotation(uid="a3", annotation_type="oval", page_uid="p2"),
            BidAnnotation(uid="a4", annotation_type="oval", page_uid=""),
            BidAnnotation(uid="a5", annotation_type="oval", page_uid=None),
        ]

    def test_set_and_get_annotations_copy_the_collections(self):
        service = PageSelectionService()
        source = self.annotations()
        service.set_annotations(source)
        source.clear()
        returned = service.get_all_annotations()
        self.assertEqual([a.uid for a in returned], ["a1", "a2", "a3", "a4", "a5"])
        returned.clear()
        self.assertEqual(len(service.get_all_annotations()), 5)

    def test_page_annotations_compare_page_uids_as_text(self):
        service = PageSelectionService()
        service.set_annotations(
            self.annotations()
            + [BidAnnotation(uid="n", annotation_type="rect", page_uid=7)]
        )
        self.assertEqual(
            [a.uid for a in service.get_page_annotations("p1")], ["a1", "a2"]
        )
        self.assertEqual([a.uid for a in service.get_page_annotations("7")], ["n"])
        self.assertEqual([a.uid for a in service.get_page_annotations(7)], ["n"])
        self.assertEqual(service.get_page_annotations("none-such"), [])

    def test_adding_nothing_leaves_the_annotations_untouched(self):
        service = PageSelectionService()
        service.set_annotations(self.annotations())
        service.add_annotations([])
        service.add_annotations(None)
        self.assertEqual(len(service.get_all_annotations()), 5)

    def test_removal_reports_each_affected_page_once_in_order_and_skips_pageless_items(
        self,
    ):
        service = PageSelectionService()
        service.set_annotations(self.annotations())
        reported = service.remove_annotations_by_keys(
            [
                ("a3", "oval"),
                ("a1", "rect"),
                ("a2", "rect"),
                ("a4", "oval"),
                ("a5", "oval"),
            ]
        )
        self.assertEqual(reported, ["p1", "p2"])
        self.assertEqual(service.get_all_annotations(), [])

    def test_removal_with_no_keys_or_no_match_changes_nothing(self):
        service = PageSelectionService()
        service.set_annotations(self.annotations())
        self.assertEqual(service.remove_annotations_by_keys([]), [])
        self.assertEqual(service.remove_annotations_by_keys(iter([])), [])
        self.assertEqual(service.remove_annotations_by_keys([("a1", "oval")]), [])
        self.assertEqual(service.remove_annotations_by_keys([("missing", "rect")]), [])
        self.assertEqual(len(service.get_all_annotations()), 5)

    def test_keys_match_uid_and_type_as_text(self):
        service = PageSelectionService()
        service.set_annotations(
            [BidAnnotation(uid=5, annotation_type="rect", page_uid="p")]
        )
        self.assertEqual(service.remove_annotations_by_keys([("5", "rect")]), ["p"])
        self.assertEqual(service.get_all_annotations(), [])
