import unittest
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyFolderInfo,
    HierarchyPageInfo,
)
from ost_visualizer.domain.entities.project_factory import build_bid


class PageFolderOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.info = HierarchyBidInfo(
            uid="8",
            name="Bid",
            folders={
                "10": HierarchyFolderInfo(
                    name="Parent",
                    pages=[HierarchyPageInfo(uid="4", name="Parent")],
                    subfolders={
                        "11": HierarchyFolderInfo(
                            name="Nested",
                            pages=[
                                HierarchyPageInfo(uid="1", name="Nested second"),
                                HierarchyPageInfo(uid="2", name="Nested first"),
                            ],
                        )
                    },
                )
            },
            pages_without_folder=[HierarchyPageInfo(uid="3", name="Root")],
        )

    def test_build_bid_sets_direct_and_nested_folder_ownership(self):
        bid = build_bid(self.info)
        self.assertEqual(bid.folders["10"].pages[0].folder_uid, "10")
        self.assertEqual(bid.folders["10"].subfolders["11"].pages[0].folder_uid, "11")
        self.assertIsNone(bid.pages_without_folder[0].folder_uid)
        self.assertEqual((bid.uid, bid.name), ("8", "Bid"))
        self.assertEqual(
            [page.uid for page in bid.folders["10"].subfolders["11"].pages], ["1", "2"]
        )
        self.assertEqual(bid.pages_without_folder[0].uid, "3")
