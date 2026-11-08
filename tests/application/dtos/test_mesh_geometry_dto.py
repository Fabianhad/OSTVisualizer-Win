import unittest
import random
from dataclasses import replace
from ost_visualizer.application.dtos.mesh_geometry_dto import (
    MeshSceneIdentity,
    normalize_scene_page_uids,
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


class NormalizeScenePageUidsTests(unittest.TestCase):
    def test_non_text_page_ids_collapse_with_their_text_form_and_sort_as_text(self):
        self.assertEqual(
            normalize_scene_page_uids([10, 9, "9", 0, None, ""]), ("10", "9")
        )
        identity = MeshSceneIdentity(BidRef("a.mdb", "b"), (2, 1, "2"), 1)
        self.assertEqual(identity.page_uids, ("1", "2"))
        self.assertEqual(
            identity, MeshSceneIdentity(BidRef("a.mdb", "b"), ("2", "1"), 1)
        )
        self.assertEqual(
            hash(identity),
            hash(MeshSceneIdentity(BidRef("a.mdb", "b"), ("2", "1"), 1)),
        )

    def test_order_is_canonical_for_many_ids_whatever_the_set_iteration_order(self):
        # Set iteration order of strings follows the per-process hash seed; with
        # 40 ids an unsorted result differs from the sorted one under every
        # seed in practice (a coincidence has probability 1/40!).
        ids = [f"page-{number:02d}" for number in range(40)]
        shuffled = ids[:]
        random.Random(5).shuffle(shuffled)
        self.assertNotEqual(shuffled, ids)
        self.assertEqual(normalize_scene_page_uids(shuffled), tuple(ids))
        self.assertEqual(normalize_scene_page_uids(reversed(ids)), tuple(ids))
        identity = MeshSceneIdentity(BidRef("a.mdb", "b"), tuple(shuffled), 1)
        self.assertEqual(identity.page_uids, tuple(ids))


class MeshGeometryValueTests(unittest.TestCase):
    def test_mesh_geometry_is_an_immutable_value(self):
        from dataclasses import FrozenInstanceError
        from ost_visualizer.application.dtos.mesh_geometry_dto import MeshGeometry

        mesh = MeshGeometry([0.0], [1.0], [0], "#fff", 1.0, "p", "c", "t")
        with self.assertRaises(FrozenInstanceError):
            mesh.opacity = 0.5
        self.assertEqual(
            mesh, MeshGeometry([0.0], [1.0], [0], "#fff", 1.0, "p", "c", "t")
        )


class MeshGeometryFieldTests(unittest.TestCase):
    def test_mesh_geometry_fields_are_keyed_by_name_and_kept_by_identity(self):
        from dataclasses import fields
        from ost_visualizer.application.dtos.mesh_geometry_dto import MeshGeometry

        vertices, normals, indices = [0.0, 1.0, 2.0], [0.0, 0.0, 1.0], [0, 1, 2]
        mesh = MeshGeometry(
            vertices=vertices,
            normals=normals,
            indices=indices,
            color="#123456",
            opacity=0.25,
            page_uid="page",
            condition_uid="condition",
            takeoff_uid="takeoff",
        )
        self.assertIs(mesh.vertices, vertices)
        self.assertIs(mesh.normals, normals)
        self.assertIs(mesh.indices, indices)
        self.assertEqual(
            (
                mesh.color,
                mesh.opacity,
                mesh.page_uid,
                mesh.condition_uid,
                mesh.takeoff_uid,
            ),
            ("#123456", 0.25, "page", "condition", "takeoff"),
        )
        self.assertEqual(
            {field.name for field in fields(MeshGeometry)},
            {
                "vertices",
                "normals",
                "indices",
                "color",
                "opacity",
                "page_uid",
                "condition_uid",
                "takeoff_uid",
            },
        )
        self.assertNotEqual(mesh, replace(mesh, vertices=[9.0]))

    def test_scene_identity_is_frozen_and_normalizes_to_a_plain_tuple_and_int(self):
        from dataclasses import FrozenInstanceError

        identity = MeshSceneIdentity(BidRef("a.mdb", "b"), ["p2", "p1"], "3")
        self.assertIs(type(identity.page_uids), tuple)
        self.assertIs(type(identity.generation), int)
        with self.assertRaises(FrozenInstanceError):
            identity.generation = 4
        with self.assertRaises(FrozenInstanceError):
            identity.page_uids = ()
        self.assertEqual(normalize_scene_page_uids([]), ())
        self.assertIs(type(normalize_scene_page_uids([])), tuple)
        self.assertIs(type(normalize_scene_page_uids(iter(["x"]))), tuple)
