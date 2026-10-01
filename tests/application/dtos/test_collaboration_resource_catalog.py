import unittest
from ost_visualizer.application.dtos.collaboration_dtos import ResourceRef
from ost_visualizer.application.dtos.collaboration_resource_catalog import (
    COLLABORATION_RESOURCE_CATALOG,
    COLLABORATION_RESOURCE_CATALOG_CHECKSUM,
    SUPPORTED_REMOTE_RESOURCE_TYPES,
    CollaborationResourceFamily,
    coalesced_resource_type,
    annotation_resource_id,
    parse_annotation_resource_id,
    resource_families_affect_page,
    resource_types_for_family,
)


class CollaborationResourceCatalogCollaborationTests(unittest.TestCase):
    def test_resource_catalog_is_canonical_and_rejects_removed_aliases(self):
        self.assertRegex(COLLABORATION_RESOURCE_CATALOG_CHECKSUM, r"^[0-9a-f]{64}$")
        self.assertNotIn("folder", COLLABORATION_RESOURCE_CATALOG)
        self.assertNotIn("folders_collection", COLLABORATION_RESOURCE_CATALOG)
        self.assertEqual(
            COLLABORATION_RESOURCE_CATALOG["condition"].family,
            CollaborationResourceFamily.CONDITIONS,
        )
        self.assertEqual(coalesced_resource_type("condition"), "conditions_collection")
        with self.assertRaisesRegex(ValueError, "Unknown collaboration resource"):
            ResourceRef("obsolete_resource", "1")

    def test_resource_family_membership_and_coalescing_preserve_scope(self):
        self.assertEqual(
            resource_types_for_family(CollaborationResourceFamily.CONDITIONS),
            {"condition", "condition_folder", "conditions_collection"},
        )
        for entity, collection, table in (
            ("page", "pages_collection", "BidPages"),
            ("takeoff", "takeoffs_collection", "BidTakeoffs"),
            ("layer", "layers_collection", "BidLayers"),
            ("area", "areas_collection", "BidAreas"),
        ):
            with self.subTest(entity=entity):
                definition = COLLABORATION_RESOURCE_CATALOG[entity]
                self.assertTrue(definition.bid_scoped)
                self.assertFalse(definition.collection)
                self.assertEqual(definition.entity_table, table)
                self.assertEqual(definition.entity_bid_column, "BidUID")
                self.assertEqual(coalesced_resource_type(entity), collection)
                self.assertEqual(coalesced_resource_type(collection), collection)
                self.assertIn(entity, SUPPORTED_REMOTE_RESOURCE_TYPES)
        self.assertFalse(
            COLLABORATION_RESOURCE_CATALOG["default_layers_collection"].bid_scoped
        )
        self.assertEqual(
            COLLABORATION_RESOURCE_CATALOG["layer"].seed_filter, "[IsTemplate]=0"
        )
        self.assertEqual(coalesced_resource_type("cover_sheet"), "cover_sheet")

    def test_annotation_identities_round_trip_without_collapsing_types(self):
        self.assertEqual(annotation_resource_id("rect", "7"), "rect/7")
        self.assertEqual(annotation_resource_id("oval", "7"), "oval/7")
        self.assertEqual(parse_annotation_resource_id("rect/7"), ("rect", "7"))
        for invalid in ("", "rect", "/7", "rect/"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                ValueError, "identity"
            ):
                parse_annotation_resource_id(invalid)
        for annotation_type, uid in (("", "7"), ("rect", ""), (None, "7")):
            with self.subTest(annotation_type=annotation_type, uid=uid):
                with self.assertRaisesRegex(ValueError, "identity"):
                    annotation_resource_id(annotation_type, uid)

    def test_affected_page_classification_distinguishes_unknown_empty_and_unrelated(
        self,
    ):
        cases = (
            ((), {}, False),
            (("takeoffs",), {}, True),
            (("takeoffs",), {"takeoffs": ()}, False),
            (("takeoffs",), {"takeoffs": ("other",)}, False),
            (("takeoffs",), {"takeoffs": ("7",)}, True),
            (("takeoffs", "pages"), {"takeoffs": (), "pages": (7,)}, True),
            (("takeoffs", "pages"), {"takeoffs": ()}, True),
        )
        for families, affected, expected in cases:
            with self.subTest(families=families, affected=affected):
                self.assertEqual(
                    resource_families_affect_page(iter(families), affected, "7"),
                    expected,
                )
