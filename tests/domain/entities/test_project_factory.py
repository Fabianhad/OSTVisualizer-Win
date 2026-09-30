import sqlite3
import unittest
from unittest.mock import Mock
from ost_visualizer.domain.aggregates.ost_aggregate import OstAggregate
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyFolderInfo,
    HierarchyPageInfo,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.project_factory import build_bid


class PageFolderOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.execute(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT, Sequence INTEGER, BidPageFolderUID INTEGER)"
        )
        self.connection.executemany(
            "INSERT INTO BidPages VALUES (?, ?, ?, ?, ?)",
            [
                (1, 8, "Nested second", 20, 11),
                (2, 8, "Nested first", 10, 11),
                (3, 8, "Root", 30, None),
                (4, 8, "Parent", 5, 10),
                (5, 9, "Other bid", 1, 11),
            ],
        )
        self.bid_ref = BidRef("database", "8")
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
        self.model = OstAggregate(Mock())
        self.model.set_hierarchy(
            HierarchyData(
                loaded_files=[
                    HierarchyFileEntry(file_path="database", orphan_bids=[self.info])
                ]
            )
        )
        self.model.current_bid_ref = self.bid_ref
        self.model.current_bid = build_bid(self.info)

    def test_build_bid_sets_direct_and_nested_folder_ownership(self):
        bid = build_bid(self.info)
        self.assertEqual(bid.folders["10"].pages[0].folder_uid, "10")
        self.assertEqual(bid.folders["10"].subfolders["11"].pages[0].folder_uid, "11")
        self.assertIsNone(bid.pages_without_folder[0].folder_uid)
