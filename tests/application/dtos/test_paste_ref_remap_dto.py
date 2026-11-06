import unittest
from ost_visualizer.application.dtos.paste_ref_remap_dto import PasteRefRemap


class PasteRefRemapTests(unittest.TestCase):
    def test_annotation_projection_matches_persisted_reference_remaps(self):
        remap = PasteRefRemap(
            takeoff_uids={"old-from": "new-from"},
            namedview_uids={"old-view": "new-view"},
        )
        original = {
            "BidTakeoffFromUID": "old-from",
            "BidTakeoffToUID": "missing-takeoff",
            "BidPageViewUID": "old-view",
            "Text": "kept",
        }
        properties = remap.remap_annotation_properties(original)
        self.assertIsNot(properties, original)
        self.assertEqual(
            original,
            {
                "BidTakeoffFromUID": "old-from",
                "BidTakeoffToUID": "missing-takeoff",
                "BidPageViewUID": "old-view",
                "Text": "kept",
            },
        )
        self.assertEqual(
            properties,
            {
                "BidTakeoffFromUID": "new-from",
                "BidPageViewUID": "new-view",
                "Text": "kept",
            },
        )

    def test_existing_named_view_reference_is_retained_without_a_remap(self):
        properties = PasteRefRemap().remap_annotation_properties(
            {"BidPageViewUID": "existing-view"}
        )
        self.assertEqual(properties, {"BidPageViewUID": "existing-view"})

    def test_empty_reference_values_match_rehydrated_model_shape(self):
        for sentinel in (None, "", "0", 0):
            with self.subTest(sentinel=sentinel):
                properties = PasteRefRemap().remap_annotation_properties(
                    {
                        "BidTakeoffFromUID": sentinel,
                        "BidTakeoffToUID": sentinel,
                        "BidPageViewUID": sentinel,
                    }
                )
                self.assertEqual(properties, {"BidPageViewUID": None})
        self.assertEqual(
            PasteRefRemap().remap_annotation_properties({"Text": "kept"}),
            {"Text": "kept"},
        )



class PasteRefRemapEdgeTests(unittest.TestCase):
    def test_emptiness_requires_both_maps_to_be_empty(self):
        self.assertIs(PasteRefRemap().is_empty(), True)
        self.assertIs(PasteRefRemap(takeoff_uids={"a": "b"}).is_empty(), False)
        self.assertIs(PasteRefRemap(namedview_uids={"a": "b"}).is_empty(), False)
        self.assertIs(PasteRefRemap({"a": "b"}, {"c": "d"}).is_empty(), False)

    def test_zero_blank_and_missing_takeoff_references_are_dropped_not_remapped(self):
        remap = PasteRefRemap(takeoff_uids={"0": "mapped-zero", "": "mapped-blank", "7": 70})
        properties = remap.remap_annotation_properties(
            {
                "BidTakeoffFromUID": "0",
                "BidTakeoffToUID": 0,
                "Other": 1,
            }
        )
        self.assertEqual(properties, {"Other": 1})
        for blank in (None, ""):
            self.assertEqual(
                remap.remap_annotation_properties({"BidTakeoffFromUID": blank, "BidTakeoffToUID": "7"}),
                {"BidTakeoffToUID": "70"},
            )
        self.assertEqual(remap.remap_annotation_properties({}), {})

    def test_page_view_references_follow_the_view_map_or_become_null_only_when_present(self):
        remap = PasteRefRemap(namedview_uids={"v": "nv", "0": "never"})
        self.assertEqual(remap.remap_annotation_properties({"BidPageViewUID": "v"}), {"BidPageViewUID": "nv"})
        self.assertEqual(remap.remap_annotation_properties({"BidPageViewUID": "unmapped"}), {"BidPageViewUID": "unmapped"})
        for blank in (None, "", "0", 0):
            self.assertEqual(remap.remap_annotation_properties({"BidPageViewUID": blank}), {"BidPageViewUID": None})
        self.assertEqual(remap.remap_annotation_properties({"Text": "t"}), {"Text": "t"})
        self.assertEqual(
            PasteRefRemap(namedview_uids={"5": 50}).remap_annotation_properties({"BidPageViewUID": 5}),
            {"BidPageViewUID": "50"},
        )


if __name__ == "__main__":
    unittest.main()
