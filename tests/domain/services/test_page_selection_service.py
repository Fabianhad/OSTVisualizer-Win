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
