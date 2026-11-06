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


class BidDefaultsAndFolderUidTests(unittest.TestCase):
    def test_bid_defaults_describe_an_empty_unmeasured_bid_with_unit_increments(self):
        bid = Bid(uid="1", name="N")
        self.assertEqual(
            (
                bid.bid_no,
                bid.bid_date,
                bid.notes,
                bid.job_id,
                bid.status,
                bid.status_uid,
                bid.estimator,
                bid.page_count,
                bid.condition_count,
                bid.measure_base,
                bid.takeoff_increments,
                bid.orig_bid_project_uid,
                bid.copy_from_bid_no,
                bid.copy_timestamp,
            ),
            (0, None, "", "", "", None, "", 0, 0, 0, 1.0, None, 0, None),
        )
        other = Bid(uid="2", name="M")
        bid.folders["x"] = Folder(uid="x", name="X")
        bid.pages_without_folder.append(Page(uid="p", name="P"))
        self.assertEqual((other.folders, other.pages_without_folder), ({}, []))

    def test_a_page_without_a_folder_is_never_assigned_to_a_folder_whose_uid_is_none_text(self):
        folder = Folder(uid="None", name="Literal None")
        bid = Bid(uid="1", name="N", folders={"None": folder})
        unassigned = Page(uid="p1", name="Loose", folder_uid=None)
        blank = Page(uid="p2", name="Blank", folder_uid="")
        owned = Page(uid="p3", name="Owned", folder_uid="None")
        bid.replace_pages([unassigned, blank, owned])
        self.assertEqual(folder.pages, [owned])
        self.assertEqual(bid.pages_without_folder, [unassigned, blank])
        self.assertEqual(bid.page_count, 3)

    def test_integer_folder_uids_match_string_page_folder_uids(self):
        folder = Folder(uid=10, name="Numeric")
        bid = Bid(uid="1", name="N", folders={10: folder})
        page = Page(uid="p", name="P", folder_uid="10")
        bid.replace_pages([page])
        self.assertEqual(folder.pages, [page])
