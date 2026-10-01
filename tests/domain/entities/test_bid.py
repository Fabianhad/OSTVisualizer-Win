import unittest
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.folder import Folder
from ost_visualizer.domain.entities.page import Page


class PageFolderOwnershipTests(unittest.TestCase):
    def test_replace_pages_accepts_its_own_root_list_and_lazy_hierarchy(self):
        for lazy in (False, True):
            with self.subTest(lazy=lazy):
                page = Page(uid="1", name="Root")
                bid = Bid(uid="8", name="Bid", pages_without_folder=[page])
                pages = (
                    (p for p in bid.pages_without_folder)
                    if lazy
                    else bid.pages_without_folder
                )
                bid.replace_pages(pages)
                self.assertEqual(bid.pages_without_folder, [page])
                self.assertEqual(bid.page_count, 1)
                self.assertIs(bid.pages_without_folder[0], page)

    def test_replacement_clears_old_folders_and_retains_exact_pages_in_sequence(self):
        stale = Page(uid="old", name="Old")
        nested = Folder(uid="nested", name="Nested", pages=[stale])
        parent = Folder(uid="parent", name="Parent", subfolders={"nested": nested})
        bid = Bid(
            uid="bid",
            name="Bid",
            folders={"parent": parent},
            pages_without_folder=[stale],
        )
        late = Page(uid="late", name="Late", sequence=20, folder_uid="nested")
        early = Page(uid="early", name="Early", sequence=1, folder_uid="nested")
        root = Page(uid="root", name="Root", sequence=2, folder_uid="missing")
        bid.replace_pages(iter([late, root, early]))
        self.assertEqual(nested.pages, [early, late])
        self.assertIs(nested.pages[0], early)
        self.assertIs(nested.pages[1], late)
        self.assertEqual(parent.pages, [])
        self.assertEqual(bid.pages_without_folder, [root])
        self.assertIs(bid.pages_without_folder[0], root)
        self.assertEqual(bid.page_count, 3)
        bid.replace_pages([])
        self.assertEqual(nested.pages, [])
        self.assertEqual(bid.pages_without_folder, [])
        self.assertEqual(bid.page_count, 0)
