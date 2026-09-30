import unittest
from ost_visualizer.application.dtos.mesh_geometry_dto import (
    MeshGeometry,
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
