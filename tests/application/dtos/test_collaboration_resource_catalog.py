import dataclasses
import hashlib
import unittest
from ost_visualizer.application.dtos.collaboration_dtos import ResourceRef
from ost_visualizer.application.dtos.collaboration_resource_catalog import (
    AREA_RESOURCE_TYPES,
    BID_CONTENT_ENTITY_RESOURCE_TYPES,
    BID_CONTENT_FAMILY_BY_RESOURCE_TYPE,
    BID_CONTENT_RESOURCE_TYPES,
    COLLABORATION_RESOURCE_CATALOG,
    COLLABORATION_RESOURCE_CATALOG_CHECKSUM,
    CONDITION_RESOURCE_TYPES,
    HIERARCHY_RESOURCE_TYPES,
    MASTER_DATA_RESOURCE_TYPES,
    SUPPORTED_REMOTE_RESOURCE_TYPES,
    CollaborationResourceFamily,
    coalesced_resource_type,
    annotation_resource_id,
    parse_annotation_resource_id,
    resource_definition,
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


_H = CollaborationResourceFamily.HIERARCHY
_C = CollaborationResourceFamily.CONDITIONS
_A = CollaborationResourceFamily.AREAS
_P = CollaborationResourceFamily.PAGES
_L = CollaborationResourceFamily.LAYERS
_T = CollaborationResourceFamily.TAKEOFFS
_N = CollaborationResourceFamily.ANNOTATIONS
_V = CollaborationResourceFamily.COVER_SHEET
_M = CollaborationResourceFamily.MASTER_DATA
# (type, family, collection, bid scoped, table, bid column, seed filter, coalesces into)
_EXPECTED_CATALOG = (
    ("database", _H, False, False, "", "", "", ""),
    ("project", _H, False, False, "BidProjects", "", "", "projects_collection"),
    ("projects_collection", _H, True, False, "", "", "", ""),
    ("project_bids", _H, True, False, "", "", "", "projects_collection"),
    ("bid", _H, False, True, "Bids", "UID", "", "projects_collection"),
    (
        "condition",
        _C,
        False,
        True,
        "BidConditions",
        "BidUID",
        "",
        "conditions_collection",
    ),
    (
        "condition_folder",
        _C,
        False,
        True,
        "BidConditionFolders",
        "BidUID",
        "",
        "conditions_collection",
    ),
    ("conditions_collection", _C, True, True, "", "", "", ""),
    ("area", _A, False, True, "BidAreas", "BidUID", "", "areas_collection"),
    ("areas_collection", _A, True, True, "", "", "", ""),
    ("page", _P, False, True, "BidPages", "BidUID", "", "pages_collection"),
    ("pages_collection", _P, True, True, "", "", "", ""),
    (
        "layer",
        _L,
        False,
        True,
        "BidLayers",
        "BidUID",
        "[IsTemplate]=0",
        "layers_collection",
    ),
    ("layers_collection", _L, True, True, "", "", "", ""),
    ("default_layers_collection", _L, True, False, "", "", "", ""),
    ("takeoff", _T, False, True, "BidTakeoffs", "BidUID", "", "takeoffs_collection"),
    ("takeoffs_collection", _T, True, True, "", "", "", ""),
    ("annotation", _N, False, True, "", "", "", "annotations_collection"),
    ("annotations_collection", _N, True, True, "", "", "", ""),
    ("cover_sheet", _V, False, True, "Bids", "UID", "", ""),
    ("job_status", _M, False, False, "JobStatuses", "", "", "job_statuses_collection"),
    ("job_statuses_collection", _M, True, False, "", "", "", ""),
    ("employee", _M, False, False, "Employees", "", "", "employees_collection"),
    ("employees_collection", _M, True, False, "", "", "", ""),
    ("pay_class", _M, False, False, "PayClasses", "", "", "pay_classes_collection"),
    ("pay_classes_collection", _M, True, False, "", "", "", ""),
    (
        "condition_type",
        _H,
        False,
        False,
        "CdnTypes",
        "",
        "",
        "condition_types_collection",
    ),
    ("condition_types_collection", _H, True, False, "", "", "", ""),
)


class CollaborationResourceCatalogContractTests(unittest.TestCase):
    def test_every_catalog_definition_matches_the_independent_table(self):
        self.assertEqual(
            sorted(COLLABORATION_RESOURCE_CATALOG),
            sorted(row[0] for row in _EXPECTED_CATALOG),
        )
        self.assertEqual(len(_EXPECTED_CATALOG), 28)
        for (
            name,
            family,
            collection,
            bid_scoped,
            table,
            bid_column,
            seed,
            coalesce,
        ) in _EXPECTED_CATALOG:
            with self.subTest(resource_type=name):
                definition = COLLABORATION_RESOURCE_CATALOG[name]
                self.assertIs(resource_definition(name), definition)
                self.assertEqual(definition.resource_type.value, name)
                self.assertIs(definition.family, family)
                self.assertIs(definition.collection, collection)
                self.assertIs(definition.bid_scoped, bid_scoped)
                self.assertEqual(definition.entity_table, table)
                self.assertEqual(definition.entity_uid_column, "UID")
                self.assertEqual(definition.entity_bid_column, bid_column)
                self.assertEqual(definition.seed_filter, seed)
                self.assertEqual(
                    definition.coalesce_type.value if definition.coalesce_type else "",
                    coalesce,
                )
                self.assertIs(definition.reconciliation_supported, True)
                self.assertEqual(coalesced_resource_type(name), coalesce or name)
                self.assertIn(name, SUPPORTED_REMOTE_RESOURCE_TYPES)
        self.assertEqual(
            SUPPORTED_REMOTE_RESOURCE_TYPES, {row[0] for row in _EXPECTED_CATALOG}
        )

    def test_catalog_is_immutable_and_unknown_types_are_rejected(self):
        with self.assertRaises(TypeError):
            COLLABORATION_RESOURCE_CATALOG["extra"] = None
        with self.assertRaises(dataclasses.FrozenInstanceError):
            COLLABORATION_RESOURCE_CATALOG["condition"].bid_scoped = False
        for unknown in ("", "Condition", "folder", "conditions"):
            with self.subTest(resource_type=unknown):
                with self.assertRaisesRegex(
                    ValueError, f"Unknown collaboration resource type: {unknown}$"
                ):
                    resource_definition(unknown)
                with self.assertRaises(ValueError):
                    coalesced_resource_type(unknown)

    def test_family_and_content_groupings_match_the_table(self):
        for family in CollaborationResourceFamily:
            with self.subTest(family=family):
                self.assertEqual(
                    resource_types_for_family(family),
                    frozenset(row[0] for row in _EXPECTED_CATALOG if row[1] is family),
                )
        self.assertEqual(
            CONDITION_RESOURCE_TYPES,
            {"condition", "condition_folder", "conditions_collection"},
        )
        self.assertEqual(AREA_RESOURCE_TYPES, {"area", "areas_collection"})
        self.assertEqual(
            HIERARCHY_RESOURCE_TYPES,
            {
                "database",
                "project",
                "projects_collection",
                "project_bids",
                "bid",
                "condition_type",
                "condition_types_collection",
            },
        )
        self.assertEqual(
            MASTER_DATA_RESOURCE_TYPES,
            {
                "job_status",
                "job_statuses_collection",
                "employee",
                "employees_collection",
                "pay_class",
                "pay_classes_collection",
            },
        )
        self.assertEqual(
            dict(BID_CONTENT_FAMILY_BY_RESOURCE_TYPE),
            {
                "page": "pages",
                "pages_collection": "pages",
                "layer": "layers",
                "layers_collection": "layers",
                "takeoff": "takeoffs",
                "takeoffs_collection": "takeoffs",
                "annotation": "annotations",
                "annotations_collection": "annotations",
            },
        )
        self.assertEqual(
            BID_CONTENT_RESOURCE_TYPES, set(BID_CONTENT_FAMILY_BY_RESOURCE_TYPE)
        )
        self.assertEqual(
            BID_CONTENT_ENTITY_RESOURCE_TYPES,
            {"page", "layer", "takeoff", "annotation"},
        )

    def test_catalog_checksum_is_the_pinned_deployed_contract(self):
        rows = []
        for (
            name,
            family,
            collection,
            bid_scoped,
            table,
            bid_column,
            seed,
            coalesce,
        ) in sorted(_EXPECTED_CATALOG):
            rows.append(
                "|".join(
                    (
                        name,
                        family.value,
                        "collection" if collection else "entity",
                        "bid" if bid_scoped else "database",
                        table,
                        "UID",
                        bid_column,
                        seed,
                        coalesce,
                        "reconcile",
                    )
                )
            )
        self.assertEqual(
            COLLABORATION_RESOURCE_CATALOG_CHECKSUM,
            hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            COLLABORATION_RESOURCE_CATALOG_CHECKSUM,
            "308246fe178dd1ee739f9b7dfff0098fed777cc8c47e7024d48caa1df0f722d8",
        )

    def test_annotation_identity_edges_and_normalization(self):
        self.assertEqual(parse_annotation_resource_id("rect/7/8"), ("rect", "7/8"))
        self.assertEqual(parse_annotation_resource_id("rect/7"), ("rect", "7"))
        with self.assertRaisesRegex(ValueError, "identity"):
            parse_annotation_resource_id(7)
        self.assertEqual(annotation_resource_id("rect", 7), "rect/7")
        self.assertEqual(annotation_resource_id(5, "7"), "5/7")
        with self.assertRaisesRegex(ValueError, "identity"):
            annotation_resource_id("rect", None)
        with self.assertRaisesRegex(ValueError, "identity"):
            annotation_resource_id("rect", "")

    def test_page_classification_normalizes_missing_pages_and_integer_ids(self):
        for page, affected, expected in (
            (None, {"takeoffs": ("",)}, True),
            (None, {"takeoffs": ("None",)}, False),
            ("", {"takeoffs": ("",)}, True),
            (7, {"takeoffs": ("7",)}, True),
            ("7", {"takeoffs": (7,)}, True),
            ("7", {"takeoffs": [7, 8]}, True),
            ("7", {"takeoffs": {8}}, False),
        ):
            with self.subTest(page=page, affected=affected):
                self.assertIs(
                    resource_families_affect_page(("takeoffs",), affected, page),
                    expected,
                )
