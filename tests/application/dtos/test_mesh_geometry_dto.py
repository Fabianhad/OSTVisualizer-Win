import unittest
from dataclasses import replace
from ost_visualizer.application.dtos.mesh_geometry_dto import (
    MeshSceneIdentity,
)
from ost_visualizer.domain.entities.identity_refs import BidRef


class MeshSceneIdentityTests(unittest.TestCase):
    def test_scene_identity_constructor_canonicalizes_order_and_duplicates(self):
        bid_ref = BidRef("a.mdb", "bid-1")
        identity = MeshSceneIdentity(
            bid_ref=bid_ref,
            page_uids=("page-b", "page-a", "page-b", ""),
            generation="7",
        )
        self.assertEqual(identity.bid_ref, bid_ref)
        self.assertEqual(identity.page_uids, ("page-a", "page-b"))
        self.assertEqual(identity.generation, 7)

    def test_scene_cache_identity_distinguishes_database_bid_pages_and_generation(self):
        identity = MeshSceneIdentity(BidRef("a.mdb", "bid-1"), ("p2", "p1"), 7)
        cache = {identity: "accepted-scene"}
        self.assertEqual(
            cache[replace(identity, page_uids=("p1", "p2", "p1"))], "accepted-scene"
        )
        for changed in (
            replace(identity, bid_ref=BidRef("b.mdb", "bid-1")),
            replace(identity, bid_ref=BidRef("a.mdb", "bid-2")),
            replace(identity, page_uids=("p1",)),
            replace(identity, generation=8),
        ):
            with self.subTest(changed=changed):
                self.assertNotIn(changed, cache)
